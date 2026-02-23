import os
import re

def replace_in_string(content):
    # Order matters: replace longer/more specific first if necessary, but here they don't overlap in a way that causes issues.
    s = content
    s = s.replace("OmniClaw", "OmniClaw")
    s = s.replace("omniclaw", "omniclaw")
    s = s.replace("OMNICLAW", "OMNICLAW")
    s = s.replace("Omniclaw", "Omniclaw")
    return s

def process_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        return # Skip binary files

    new_content = replace_in_string(content)
    if new_content != content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated content in {file_path}")

def main():
    root_dir = "/home/abiorh/omnuron-labs/omniclaw"
    skip_dirs = {'.git', '.venv', '.pytest_cache', '.ruff_cache', 'dist', '__pycache__'}

    # Process contents and rename files
    for dirpath, dirnames, filenames in os.walk(root_dir, topdown=False):
        # Exclude directories
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        
        # Skip processing if we're inside a skipped directory (just in case topdown=False overrides)
        if any(part in skip_dirs for part in dirpath.split(os.sep)):
            continue

        for filename in filenames:
            file_path = os.path.join(dirpath, filename)
            process_file(file_path)

            new_filename = replace_in_string(filename)
            if new_filename != filename:
                new_file_path = os.path.join(dirpath, new_filename)
                os.rename(file_path, new_file_path)
                print(f"Renamed file: {file_path} -> {new_file_path}")

        for dirname in dirnames:
            new_dirname = replace_in_string(dirname)
            if new_dirname != dirname:
                dir_path = os.path.join(dirpath, dirname)
                new_dir_path = os.path.join(dirpath, new_dirname)
                os.rename(dir_path, new_dir_path)
                print(f"Renamed dir: {dir_path} -> {new_dir_path}")

if __name__ == "__main__":
    main()
