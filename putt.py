from __future__ import print_function
import re
import pickle
import shutil
import subprocess
import shlex
import json
from tempfile import NamedTemporaryFile
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from pathlib import Path
import time

START_ROW = 2

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
DATE_RANGE = f"%s!A{START_ROW}:A"
LAST_DATA_RANGE = f"%s!A%d:F%d"
APPEND_RANGE = "%s!A%d:F%d"

CONFIG_PATH = Path.home().joinpath(".config", "putt")
CREDENTIALS_FILE_PATH = CONFIG_PATH.joinpath("credentials.json")
CONFIG_FILE_PATH = CONFIG_PATH.joinpath("config.json")

DATA_PATH = Path.home().joinpath(".putt")
TOKEN_PICKLE_PATH = DATA_PATH.joinpath("token.pickle")


class ConfigNotFoundError(Exception):
    pass


class CredentialsNotFoundError(Exception):
    pass


def putt():
    CONFIG_PATH.mkdir(parents=True, exist_ok=True)
    DATA_PATH.mkdir(parents=True, exist_ok=True)

    vim_command = "nvim" if shutil.which("nvim") else "vim"

    vim_commands = " | ".join(
        [
            "syn clear",
            r"syntax match Boolean /\(.\+\)\@<!\zs\(n\|y\)\ze\s*\([^\#]\)\@!/",
            r"syntax match Comment /\#.*/",
            r"syntax match String /\".*\"/",
            "highlight ExtraWhitespace ctermbg=red guibg=red",
            r"match ExtraWhitespace /\s\+$/",
        ]
    )

    input_file_boilerplate = "\n".join(
        [
            "",
            "",
            "",
            "",
            "# y                                productive (y/n)",
            "# park visit                       description",
            "# 1:05                             time estimate hh:mm",
            "# hanging out with some friends    detail",
        ]
    )

    valid_input = True
    with NamedTemporaryFile("w") as temp_file:
        temp_file.seek(0)
        temp_file.write(input_file_boilerplate)
        temp_file.flush()
        subprocess.run(
            shlex.split(f'{vim_command} -c "{vim_commands}" {temp_file.name}'),
        )
        with open(temp_file.name) as read_temp_file:
            try:
                productive, description, estimate, detail = map(
                    lambda s: s.strip(), read_temp_file.readlines()[:4]
                )
                if not productive or not description:
                    valid_input = False
            except ValueError as e:
                print(e)
                valid_input = False

    productive = (
        "Y"
        if re.match(
            r"y(es)?|t(rue)?",
            productive,
            flags=re.RegexFlag.I,
        )
        else "N"
    )

    estimate = [*map(int, reversed(estimate.split(":")))]

    if not estimate:
        valid_input = False
    elif len(estimate) == 1:
        (estimate,) = estimate
    else:
        estimate = estimate[0] + 60 * estimate[1]

    estimate = (datetime.now() + timedelta(minutes=estimate)).strftime("%X")

    if not valid_input:
        print("Empty or invalid input")
        return

    if not CONFIG_FILE_PATH.exists():
        raise CredentialsNotFoundError(f"Couldn't find config at {CONFIG_FILE_PATH}")

    with open(CONFIG_FILE_PATH) as config_file:
        config = json.load(config_file)

    spreadsheet_id = config["spreadsheet_id"]

    creds = None
    if TOKEN_PICKLE_PATH.exists():
        with open(TOKEN_PICKLE_PATH, "rb") as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE_PATH.exists():
                raise CredentialsNotFoundError(
                    f"Couldn't find credentials at {CREDENTIALS_FILE_PATH}"
                )

            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE_PATH, SCOPES
            )
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(TOKEN_PICKLE_PATH, "wb") as token:
            pickle.dump(creds, token)

    service = build("sheets", "v4", credentials=creds)

    now = datetime.now()
    month_name = now.strftime("%B")
    date_range = DATE_RANGE % month_name
    # Call the Sheets API
    sheet = service.spreadsheets()
    result = (
        sheet.values().get(spreadsheetId=spreadsheet_id, range=date_range).execute()
    )
    values = result.get("values", [])
    last_row = len(values) + START_ROW - 1

    update_range = APPEND_RANGE % (month_name, *[last_row + 1] * 2)
    print("Writing activity...")
    put_result = (
        sheet.values()
        .update(
            spreadsheetId=spreadsheet_id,
            body={
                "values": [
                    [
                        now.strftime("%m/%d/%Y"),
                        now.strftime("%X"),
                        description,
                        productive,
                        estimate,
                        detail,
                    ]
                ]
            },
            range=update_range,
            valueInputOption="USER_ENTERED",
        )
        .execute()
    )


if __name__ == "__main__":
    putt()

