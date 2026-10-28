import re

UNITS = {
    "zero": 0, "one": 1, "won": 1, "two": 2, "three": 3, "tree": 3, "free": 3,
    "four": 4, "for": 4, "fore": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "ate": 8, "nine": 9,
}
TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}
MAX_POSITION = 23


def tokenize(text):
    return re.findall(r"[a-z]+|\d+", text.lower())


def numbers_from_text(text):
    """Extract board positions (0-23) in spoken order."""
    tokens = tokenize(text)
    found = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.isdigit():
            found.append(int(tok))
        elif tok == "twenty":
            value = 20
            if i + 1 < len(tokens) and tokens[i + 1] in ("one", "two", "three"):
                value += UNITS[tokens[i + 1]]
                i += 1
            found.append(value)
        elif tok in TEENS:
            found.append(TEENS[tok])
        elif tok in UNITS:
            found.append(UNITS[tok])
        i += 1
    return [n for n in found if 0 <= n <= MAX_POSITION]


def parse_command(text):
    text = (text or "").lower().strip()
    tokens = set(tokenize(text))
    nums = numbers_from_text(text)

    if tokens & {"restart", "reset", "new"}:
        return {"action": "restart"}
    if tokens & {"quit", "exit"}:
        return {"action": "quit"}
    if "menu" in tokens:
        return {"action": "menu"}

    # Speech engines often hear "move 4 to 5" as "move 4 2 5".
    if len(nums) == 3 and nums[1] == 2:
        nums = [nums[0], nums[2]]

    if tokens & {"remove", "capture", "take", "delete", "kill"}:
        if nums:
            return {"action": "remove", "position": nums[0]}
        return {"action": "unknown"}

    if tokens & {"move", "from", "slide", "fly", "jump"} and len(nums) >= 2:
        return {"action": "move", "source": nums[0], "target": nums[1]}

    if tokens & {"place", "put", "position", "at", "play", "go", "select", "click"}:
        if nums:
            return {"action": "place", "position": nums[0]}

    if len(nums) == 2:
        return {"action": "move", "source": nums[0], "target": nums[1]}
    if len(nums) == 1:
        return {"action": "place", "position": nums[0]}

    return {"action": "unknown"}
