PASSAGE_A = """The old harbour town wakes up slowly. At six, the first fishing boats come back with there
nets full, and the gulls follow them in long, noisy circles. By seven, the bakery on the
corner has opened it's shutters, and the smell of fresh bread drifts down to the water. The
harbour master walks along the peir with a clipboard, counting boats and checking ropes. He
has done this every morning for twenty-two years, and he still writes everything by hand.
Tourists start to arrive around nine. They take photos of the lighthouse, buy ice cream they
dont really want, and ask the fishermen questions they have heard a thousand times. Most of
the fishermen answer politely. One of them, a tall man called Piet, tells every visitor a
diferent story about the lighthouse ghost. By noon the market square is full. Farmers sell
cheese, honey and apples from wooden stalls, and a man with an acordion plays the same three
songs untill the church bell rings. In the afternoon the wind picks up, and the boats stay
in. The town goes quiet again, as if it is resting before tommorow."""
FILE_B = '''import json
from pathlib import Path


def load_orders(path):
    with Path(path).open() as handle:
        return json.load(handle)


def summarise(orders):
    count = 0
    total = 0.0
    biggest = None
    for order in orders:
        count += 1
        total += order["amount"]
        if biggest is None or order["amount"] > biggest["amount"]:
            biggest = order
    average = total / count if count else 0.0
    return {"count": count, "total": total, "average": average, "biggest": biggest}


def report(summary):
    lines = [
        f"orders: {summary['count']}",
        f"total: {summary['total']:.2f}",
        f"average: {summary['average']:.2f}",
    ]
    if summary["biggest"] is not None:
        lines.append(f"biggest: {summary['biggest']['id']}")
    return "\\n".join(lines)


if __name__ == "__main__":
    import sys
    print(report(summarise(load_orders(sys.argv[1]))))'''
LIST_C = """Weekend hike packing list
Rain jacket with a hood
Warm fleece for the evening
Two pairs of thick socks
Walking boots, broken in
Water bottle, one litre
Trail map and a compass
Sandwiches for both days
A bag of nuts and raisins
Small first-aid kit
Head torch with spare batteries
Sun cream and a hat
Phone, fully charged
A plastic bag for rubbish"""
SYSTEM = "You are a helpful assistant."
W = {
 "quote": {"max_tokens": 1024, "think": False, "temperature": 0, "prompts": {
   "Q1": "Fix the spelling mistakes in this text. Change nothing else, and return the full corrected text only.\n\n" + PASSAGE_A,
   "Q2": "In this Python file, rename the local variable count in summarise() to n_items. Keep the dictionary key \"count\" as it is. Return the complete file and nothing else.\n\n" + FILE_B,
   "Q3": "Put the line number and a full stop at the start of every line of this list, change nothing else, and return the whole list.\n\n" + LIST_C}},
 "prose": {"max_tokens": 600, "think": False, "temperature": 0, "prompts": {
   "P1": "In about 400 words, explain to a twelve-year-old how the gears on a bicycle make hills easier.",
   "P2": "In about 400 words, describe a rainy morning in a small bakery from the baker's point of view.",
   "P3": "In about 400 words, explain why bread goes stale, for a curious adult with no chemistry background."}},
 "code": {"max_tokens": 800, "think": False, "temperature": 0, "prompts": {
   "K1": "Write a Python function parse_duration(text) that turns strings like \"1h 30m\", \"45s\" or \"2h5m10s\" into a number of seconds. Include a docstring and five assert tests.",
   "K2": "Write a small Python command-line script that counts the words in a text file and prints the ten most common words with their counts. Use only the standard library.",
   "K3": "Write a JavaScript function debounce(fn, ms) with a short usage example."}},
 "think": {"max_tokens": 1024, "think": True, "temperature": 0.6, "prompts": {
   "T1": "How many three-digit numbers have digits that add up to 20 and are divisible by 7? List them.",
   "T2": "In how many different ways can you make 1 euro from coins of 10, 20 and 50 cents?",
   "T3": "What is the smallest positive whole number that leaves remainder 2 when divided by 3, remainder 3 when divided by 5 and remainder 4 when divided by 7?"}},
}
METHODS = {
 "none": ["--spec-type", "none"],
 "draft_n3": ["-md", "/Volumes/T7 Touch/models/Qwen3-0.6B-Q8_0.gguf", "-ngld", "all", "--spec-type", "draft-simple"],
 "draft_n8": ["-md", "/Volumes/T7 Touch/models/Qwen3-0.6B-Q8_0.gguf", "-ngld", "all", "--spec-type", "draft-simple", "--spec-draft-n-max", "8"],
 "ngram_simple": ["--spec-type", "ngram-simple"],
}
