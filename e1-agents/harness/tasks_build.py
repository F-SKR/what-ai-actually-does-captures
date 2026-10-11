"""Builds the ten task folders (fixed content, no randomness at run time)."""
import os, json, hashlib, shutil
SYSTEM = ("You are a helpful assistant working in a folder on the user's computer. Solve the user's task. "
          "When you are done, reply with your final answer. Put it on the last line, starting with ANSWER:")
NOTES = ["Remember to water the plants on Sunday.", "Dentist appointment moved to the second Tuesday.", "Buy oat milk and batteries.",
 "The garage door code was changed last month.", "Call Sam about the bike repair.", "Return the library books before they are due.",
 "Birthday gift ideas: a book, a scarf, tea.", "Recycling goes out on Thursday night.", "The car insurance renews in autumn.",
 "Try the new bakery on Elm Street.", "Pick up the parcel from the post office.", "Fix the squeaky hinge on the pantry door.",
 "Neighbours are away until the 20th.", "The printer needs a new black cartridge.", "Plan the route for the weekend hike.",
 "Back up the photos to the external drive.", "Boiler serviced on 2026-03-14. Next check due in March.", "Order a replacement shower curtain.",
 "Ask the landlord about the leaking tap.", "Update the emergency contact list.", "The smoke alarm battery chirps again.",
 "Sort the tools in the shed.", "Renew the passport before the trip.", "Compost bin is full.", "Write the thank-you cards.",
 "Check the tyre pressure.", "Subscribe to the local farm box.", "The thermostat schedule needs a winter update.",
 "Pay the water bill by the 5th.", "Clean the gutters before the rains."]
assert len(NOTES) == 30 and "Boiler" in NOTES[16]
SHOPS = ["Corner Market", "Green Grocer", "Hardware Hub", "Bakery Row", "Paper & Pens", "City Pharmacy"]
AMOUNTS = ["84.20", "12.50", "156.75", "33.10", "210.00", "47.95", "9.99", "128.40", "75.25", "301.50", "61.30", "163.71"]
assert round(sum(float(a) for a in AMOUNTS), 2) == 1284.65, sum(float(a) for a in AMOUNTS)
MATHUTIL = "def mean(xs):\n    return sum(xs) / (len(xs) - 1)\n"
TEST = ("import unittest\nfrom mathutil import mean\n\nclass TestMean(unittest.TestCase):\n"
        "    def test_three(self):\n        self.assertEqual(mean([2, 4, 6]), 4)\n    def test_one(self):\n        self.assertEqual(mean([5]), 5)\n\n"
        "if __name__ == '__main__':\n    unittest.main()\n")

def log_lines():
    # 500 lines; exactly 37 contain ERROR, picked by a fixed arithmetic rule
    err = set(); i = 5
    while len(err) < 37:
        err.add(i % 500); i += 13
    levels = ["INFO", "DEBUG", "WARN"]
    out = []
    for n in range(500):
        lvl = "ERROR" if n in err else levels[n % 3]
        out.append(f"2026-03-{(n // 20) % 28 + 1:02d} {(n * 7) % 24:02d}:{(n * 13) % 60:02d}:{(n * 29) % 60:02d} {lvl} worker-{n % 6} request {1000 + n} status {200 if lvl != 'ERROR' else 500}")
    assert sum("ERROR" in l for l in out) == 37
    return "\n".join(out) + "\n"

TASKS = {
 "T01": dict(category="lookup", prompt="What is the Wi-Fi password written in the file house/wifi.txt?", answer="plum-otter-4471", check="contains",
             files={"house/wifi.txt": "Network: attic-5g\nPassword: plum-otter-4471\n"}),
 "T02": dict(category="lookup", prompt="Somewhere in the folder notes/ there is a note about the boiler. On what date was the boiler last serviced? Answer as YYYY-MM-DD.",
             answer="2026-03-14", check="contains", files={f"notes/note-{i+1:02d}.txt": NOTES[i] + "\n" for i in range(30)}),
 "T03": dict(category="lookup", prompt="How many lines in the file logs/server.log contain the word ERROR?", answer="37", check="int", files={"logs/server.log": log_lines()}),
 "T04": dict(category="lookup", prompt="What is the total of the amount column in receipts.csv? Give it with two decimals.", answer="1284.65", check="num",
             files={"receipts.csv": "date,shop,amount\n" + "".join(f"2026-02-{i+1:02d},{SHOPS[i % 6]},{AMOUNTS[i]}\n" for i in range(12))}),
 "T05": dict(category="compute", prompt="What is 48317 multiplied by 9264?", answer="447608688", check="int", files={}),
 "T06": dict(category="compute", prompt="What is 17.5% of 2348.40? Round to two decimals.", answer="410.97", check="num", files={}),
 "T07": dict(category="compute", prompt="What day of the week was 14 March 2019?", answer="Thursday", check="word", files={}),
 "T08": dict(category="code", prompt="The test in test_mathutil.py fails. Fix the one-line bug in mathutil.py so that the test passes. Here are both files:\n\n"
             "mathutil.py:\n```python\n" + MATHUTIL + "```\n\ntest_mathutil.py:\n```python\n" + TEST + "```\n\nWhen you are done, reply with the full corrected mathutil.py in one code block.",
             answer="the denominator is len(xs)", check="code", files={"mathutil.py": MATHUTIL, "test_mathutil.py": TEST}),
 "T09": dict(category="control", prompt="Put these words in alphabetical order: pear, apple, mango, cherry, banana, kiwi.", answer="apple, banana, cherry, kiwi, mango, pear", check="order", files={}),
 "T10": dict(category="control", prompt="What is the capital city of Australia? Answer with one word.", answer="Canberra", check="word", files={}),
}

def build(task_id, folder):
    if os.path.exists(folder): shutil.rmtree(folder)
    os.makedirs(folder)
    for rel, text in TASKS[task_id]["files"].items():
        p = os.path.join(folder, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(text)

def folder_files(task_id):
    return {rel: hashlib.sha256(t.encode()).hexdigest() for rel, t in TASKS[task_id]["files"].items()}
