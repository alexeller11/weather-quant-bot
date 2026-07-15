import os

def search_files(dir_path, query):
    for root, dirs, files in os.walk(dir_path):
        if ".git" in root or "node_modules" in root:
            continue
        for file in files:
            if file.endswith(".py") or file.endswith(".json") or file.endswith(".yaml"):
                path = os.path.join(root, file)
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        for i, line in enumerate(f, 1):
                            if query.lower() in line.lower():
                                print(f"{file}:{i} -> {line.strip()}")
                except Exception as e:
                    pass

search_files(".", "los angeles")
search_files(".", "los-angeles")
