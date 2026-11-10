import json


def read_package_json(file_path):
    with open(file_path, "r", encoding="utf-8-sig") as file:
        return json.load(file)


def detect_npm_scripts(file_path):
    try:
        data = read_package_json(file_path)

        if not isinstance(data, dict):
            raise ValueError("package.json must contain a JSON object")

        scripts = data.get("scripts", {})

        if not isinstance(scripts, dict):
            raise ValueError("scripts must be a JSON object")

        return {
            "build": scripts.get("build"),
            "test": scripts.get("test"),
            "error": None,
        }

    except (json.JSONDecodeError, UnicodeError, OSError, ValueError) as error:
        return {"build": None, "test": None, "error": str(error)}


def find_build_files(repo_path, file_names):
    found_files = []

    ignored_dirs = {"node_modules", ".git", ".venv", "venv", "dist", "build"}

    for filename in file_names:
        for file_path in repo_path.rglob(filename):

            relative_parts = file_path.relative_to(repo_path).parts

            if any(part in ignored_dirs for part in relative_parts[:-1]):
                continue

            if file_path.is_file():
                found_files.append(file_path)

    return sorted(set(found_files))


def detect_package_manager(repo_path):
    package_managers = {
        "pnpm-lock.yaml": "pnpm",
        "package-lock.json": "npm",
        "yarn.lock": "yarn",
        "bun.lock": "bun",
        "bun.lockb": "bun",
    }

    lock_files = find_build_files(repo_path, list(package_managers.keys()))

    results = []

    for file_path in lock_files:
        filename = file_path.name
        manager = package_managers.get(filename)

        results.append(
            {
                "directory": str(file_path.parent.relative_to(repo_path)),
                "package_manager": manager,
                "lock_file": filename,
            }
        )

    return results
