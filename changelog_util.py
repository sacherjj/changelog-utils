#!/usr/bin/env python3

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys


def cli(*arguments) -> int:
    """
    Parse list of method line arguments and call appropriate method.
    """

    class Parser:
        def __init__(self):
            self.parser = argparse.ArgumentParser(prog="changelog_util")
            self.sp = self.parser.add_subparsers(help="Choose a request")

            def no_command():
                print("You must provide a method. --help for documentation of commands.")
                self.parser.print_usage()
                return 1

            self.parser.set_defaults(function=no_command)

        def add_command(self, command_name: str, function, help_message: str, argument_list: list):
            """ Add main command to parser """
            command_parser = self.sp.add_parser(command_name, help=help_message)
            command_parser.set_defaults(function=function)
            for (args, options) in argument_list:
                command_parser.add_argument(*args, **options)

        def run(self, argv):
            # Using dict rather than namespace to allow dual interface with library
            kwargs = vars(self.parser.parse_args(argv))
            method = kwargs["function"]
            del kwargs["function"]

            return method(**kwargs)

    parser = Parser()

    HELP: str = (
        "Calculate and return the account hash from public key and algorithm pair."
        "Saves in file if path given, otherwise uses stdout."
    )
    version_options = [
        (("-s", "--source"),
         dict(required=True, type=str, help="Path to the input changelog file.")),
        (("-t", "--target"),
         dict(required=True, type=str, help="Path to the output changelog file.")),
        (("-o", "--overwrite",),
         dict(required=False, default=False, action="store_true", help="Allow overwriting of target file.")),
        (("-v", "--version"),
         dict(required=True, type=str, help="SemVer text for heading and release link.")),
        (("-l", "--label"),
         dict(required=False, type=str, default=None,
              help="Label for section.  If omitted, today's date in yyyy-mm-dd format is used.")),
        (("-u", "--unreleased"),
         dict(required=False, default=False, action="store_true", help="Include new Unreleased section and compare."))
    ]
    parser.add_command("version",
                       bump_version,
                       "Promote Unreleased section to a versioned section.",
                       version_options)

    version_files_options = [
        (("-f", "--files"),
         dict(required=True, type=str,
              help=("JSON file array of Label, File Paths to combine. "
                    'ex: [["Label 1", "full_path_to/CHANGELOG.md"], ["Label 2", "full_path/CHANGELOG.md"]]'))),
        (("-v", "--version"),
         dict(required=True, type=str, help="SemVer text for heading and release link.")),
        (("-l", "--label"),
         dict(required=False, type=str, default=None, dest="label",
              help="Label for section.  If omitted, today's date in yyyy-mm-dd format is used.")),
        (("-u", "--unreleased"),
         dict(required=False, default=False, action="store_true", help="Include new Unreleased section and compare."))
    ]
    parser.add_command("version-files",
                       version_files,
                       "Promote Unreleased section to a versioned section inplace for file paths from JSON.",
                       version_files_options)

    combine_options = [
        (("-f", "--files"),
         dict(required=True, type=str,
              help=("JSON file array of Label, File Paths to combine. "
                    'ex: [["Label 1", "full_path_to/CHANGELOG.md"], ["Label 2", "full_path/CHANGELOG.md"]]'))),
        (("-t", "--target"),
         dict(required=True, type=str, help="Path to the output changelog file.")),
        (("-o", "--overwrite",),
         dict(required=False, default=False, action="store_true", help="Allow overwriting of target file.")),
        (("-u", "--unreleased"),
         dict(required=False, default=False, action="store_true", help="Include Unreleased section and compare."))
    ]
    parser.add_command("combine",
                       combine_files,
                       "Integrate multiple changelog files into a single file.",
                       combine_options)
    return parser.run([str(a) for a in arguments])


re_number_heading = re.compile("##\s\[([0-9]*.[0-9]*.[0-9]*)\] - ([0-9]*-[0-9]*-[0-9]*)")
re_unreleased_header = re.compile("##\s\[Unreleased\]")
re_links_start = re.compile("\[Keep a Changelog\]")
github_compare = "https://github.com/casper-network/casper-node/compare/"
re_unreleased_link = re.compile(f"\[unreleased\]: {github_compare}(v.[0-9]*.[0-9]*.[0-9]*)...dev")

casper_node_changelogs = (
    ("Casper Node (node/)", "node/CHANGELOG.md"),
    ("Execution Engine (execution_engine/)", "execution_engine/CHANGELOG.md"),
    ("Node Macros (node_macros/)", "node_macros/CHANGELOG.md"),
    ("Casper Types (types/)", "types/CHANGELOG.md"),
    ("Cargo Casper (execution_engine_testing/cargo_casper)", "execution_engine_testing/cargo_casper/CHANGELOG.md"),
    ("Test Support (execution_engine_testing/test_support)", "execution_engine_testing/test_support/CHANGELOG.md"),
    ("Contract (smart_contracts/contract)", "smart_contracts/contract/CHANGELOG.md"),
    ("Contract AssemblyScript (smart_contracts/contract_as)", "smart_contracts/contract_as/CHANGELOG.md"),
)

MAX_EMPTY_LINES = 3

SCRIPT_DIR = Path(__file__).parent.absolute()
CASPER_NODE_DIR = SCRIPT_DIR.parent / "casper-node"


def _get_changelog_sections(changelog_text: list):
    """
    Breaks changelog into

    :param changelog_text: list of lines from the changelog file
    :return: list of (section_name, list of lines)
    """
    sections = []
    section = 'top'
    section_data = []
    for line in changelog_text:
        unreleased_match = re_unreleased_header.match(line)
        num_header_match = re_number_heading.match(line)
        links_start_match = re_links_start.match(line)
        if unreleased_match:
            sections.append((section, section_data))
            section = 'unreleased'
            section_data = []
        elif num_header_match:
            sections.append((section, section_data))
            section = num_header_match.group(1)
            section_data = []
        elif links_start_match:
            sections.append((section, section_data))
            section = 'bottom'
            section_data = []
        section_data.append(line)
    sections.append((section, section_data))
    return sections


def _section_has_changes(section_data) -> bool:
    """
    Looks for a section containing something other than "No changes."

    :param section_data: list of lines
    :return: boolean
    """
    non_empty_lines = [line.strip() for line in section_data[1:] if line.strip()]
    if len(non_empty_lines) == 0:
        return False
    if len(non_empty_lines) == 1:
        if "no changes" in non_empty_lines[0].lower():
            return False
    return True


def combine_files(files: str, target: str, overwrite: bool, unreleased: bool):
    """
    Combine multiple changelog.md files into single changelog.md file.
    Changes will be integrated into the same sections in the order given.

    :param files: JSON file with an array of label, file paths to process
    :param target: path to save file
    :param overwrite: flag to allow overwrite if target exists
    :param unreleased: flag for including new Unreleased section and compare link at the end
    :return: exit code
    """
    json_file = Path(files)
    json_data = json.loads(json_file.read_text())
    section_set = set()
    all_files = []
    for label, file_path in json_data:
        file_data = Path(file_path).read_text().splitlines()
        sections = _get_changelog_sections(file_data)
        all_files.append((label, sections))
        for name, section_data in sections:
            section_set.add(name)
    section_set.difference_update({"top", "unreleased", "bottom"})

    # Start output with the top section of the first file.
    output = [[line for line in section_data] for name, section_data in all_files[0][1] if name == "top"][0]
    section_list = sorted(list(section_set), reverse=True)
    if unreleased:
        section_list.insert(0, "unreleased")
    # Combine sections
    for section_name in section_list:
        first_line = False
        for label, sections in all_files:
            for name, section_data in [(nm, sd) for nm, sd in sections if nm == section_name]:
                if not first_line:
                    output.append(section_data[0])
                    first_line = True
                if not _section_has_changes(section_data):
                    continue
                output.extend(["", f"### {label}"])
                # Assumes leading whitespace after first line and strips to one empty line.
                # Bumping change type down one level due to new label section
                output.extend([line.replace("###", "####")
                               for line in _clean_extra_empty_lines(section_data[1:], 1)])
    # Add bottom links from first file
    for section_data in [section_data for name, section_data in all_files[0][1] if name == "bottom"]:
        for line in section_data:
            if not unreleased and re_unreleased_link.match(line):
                continue
            output.append(line)

    output_file = Path(target)
    if output_file.exists() and not overwrite:
        print(f"target file: {target} exists, but overwrite flag not provided. Aborting.")
        return 1

    output_file.write_text("\n".join(output))
    return 0


def _clean_extra_empty_lines(text_lines: list, line_count: int = MAX_EMPTY_LINES) -> list:
    """
    Trims more than line_count empty lines

    :param text_lines: file_text as list of str
    :return: list of str
    """
    output = []
    clean_line_count = 0
    for line in text_lines:
        line = line.strip()
        if line == "":
            clean_line_count += 1
        else:
            clean_line_count = 0
        if clean_line_count <= line_count:
            output.append(line)
    return output


def version_files(files: str, version: str, unreleased: bool, label: str = None) -> int:
    json_file = Path(files)
    json_data = json.loads(json_file.read_text())
    for _, file_path in json_data:
        bump_version(file_path, file_path, True, version, unreleased, label)


def bump_version(source: str, target: str, overwrite: bool, version: str, unreleased: bool, label: str = None) -> int:
    """
    Creates sem ver section to replace Unreleased section and compare link in changelog file.

    :param source: path to source file
    :param target: path to save file
    :param overwrite: flag to allow overwrite if target exists
    :param version: semver to use for Unreleased section
    :param unreleased: flag for including new Unreleased section and compare link at the end
    :param label: label to use with section, default to today's date in yyyy-mm-dd if missing.
    :return: exit code
    """
    if label is None:
        label = datetime.today().strftime('%Y-%m-%d')

    source_text = Path(source).read_text().splitlines()
    target_file = Path(target)
    if target_file.exists() and not overwrite:
        print(f"target file: {target} exists, but overwrite flag not provided. Aborting.")
        return 1

    output = []
    for line in source_text:
        link_match = re_unreleased_link.match(line)
        if link_match:
            if unreleased:
                output.append(f"[unreleased]: {github_compare}v{version}...dev")
            output.append(f"[{version}]: {github_compare}{link_match.group(1)}...v{version}")
            continue
        if re_unreleased_header.match(line):
            if unreleased:
                output.append(line)
                output.extend(["\n", "No changes.", "\n", "\n", "\n"])
            output.append(f"## [{version}] - {label}")
            continue
        output.append(line)
    output = _clean_extra_empty_lines(output)
    target_file.write_text("\n".join(output))
    return 0


def main():
    return cli(*sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
