from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

import yaml

LANGUAGES_FILE = Path(__file__).parent / "data" / "languages.yml"


def load_language_definitions():
    with LANGUAGES_FILE.open(encoding="utf-8") as file:
        return yaml.safe_load(file)


def build_language_index(definitions):
    extension_index = defaultdict(set)
    filename_index = defaultdict(set)

    for language, details in definitions.items():

        for extension in details.get("extensions", []):
            extension_index[extension.lower()].add(language)

        for filename in details.get("filenames", []):
            filename_index[filename.lower()].add(language)

    return extension_index, filename_index


def detect_languages(files: list[str]):
    definitions = load_language_definitions()
    extension_index, filename_index = build_language_index(definitions)

    language_counts = Counter()
    ambiguous_files = []
    unknown_files = []

    extensions = sorted(extension_index, key=len, reverse=True)

    for file in files:
        filename = PurePosixPath(file).name.lower()

        candidates = set(filename_index.get(filename, set()))

        if not candidates:
            for extension in extensions:
                if filename.endswith(extension):
                    candidates = extension_index[extension]
                    break

        if len(candidates) == 1:
            language = next(iter(candidates))

            if definitions[language].get("type") == "programming":
                language_counts[language] += 1

        elif len(candidates) > 1:
            ambiguous_files.append(
                {"file": file, "possible_languages": sorted(candidates)}
            )

        else:
            unknown_files.append(file)

    return {
        "languages": [
            {"name": name, "file_count": count}
            for name, count in language_counts.most_common()
        ],
        "ambiguous_files": ambiguous_files,
        "unknown_file_count": len(unknown_files),
    }
