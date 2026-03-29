
path = "app/domains/validators/dc_bias_validator.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

new_content = content.replace(
    "if topology in {\"inverting\", \"non_inverting\"}:\n            rf = c.RC\n            rin = c.RE if c.RE > 0 else c.R2",
    "if topology in {\"inverting\", \"non_inverting\"} or \"inverting\" in topology or \"non_inverting\" in topology:\n            rf = c.RC\n            rin = c.RE if c.RE > 0 else c.R2"
)

with open(path, "w", encoding="utf-8") as f:
    f.write(new_content)

print("Check success")

