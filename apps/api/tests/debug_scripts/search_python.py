import os

targets = ["khác yêu cầu"]

for root, _, files in os.walk("app"):
    for file in files:
        if file.endswith(".py"):
            with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                content = f.read()
                for target in targets:
                    if target in content:
                        print(f"Found {target} in {os.path.join(root, file)}")

print("Search done.")
