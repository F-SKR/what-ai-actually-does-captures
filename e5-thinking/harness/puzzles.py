SYSTEM_A = ("Solve the puzzle. End your reply with exactly one final line of the form ANSWER: <your answer>, with nothing after it. "
            "Give only the answer on that line: no units, no extra words.")
CODE = {
"C01": "x = [1, 2, 3]\ny = x\ny.append(4)\nprint(len(x))\n",
"C02": "total = 0\nfor i in range(1, 10, 3):\n    total += i * i\nprint(total)\n",
"C03": "s = \"banana\"\nprint(s.count(\"an\") + s.find(\"n\"))\n",
"C04": "def f(n):\n    return n if n < 2 else f(n - 1) + f(n - 2)\nprint(f(10))\n",
"C05": "d = {}\nfor w in \"the cat and the hat\".split():\n    d[w] = d.get(w, 0) + 1\nprint(sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[0][0])\n",
"C06": "a = [3, 1, 2]\nb = sorted(a)\na.sort(reverse=True)\nprint(a[0] - b[0], b == a[::-1])\n",
}
def code_msg(cid): return "What does this Python program print?\n\n```python\n" + CODE[cid] + "```"
P = [
("W01","word","A train leaves at 09:40. The trip takes 2 hours 55 minutes, and it is delayed by 25 minutes on the way. At what time does it arrive? Answer as HH:MM.","13:00","time"),
("W02","word","A shop sells pens at 3 for 2 euros. A pen that does not make a full group of 3 costs 1 euro. Ana buys 14 pens. How many euros does she pay?","10","num"),
("W03","word","A tank holds 240 litres and is 3/8 full. You add 45 litres, then use a quarter of what is in the tank. How many litres are left?","101.25","num"),
("W04","word","Mia is 3 times as old as her son. In 12 years she will be twice as old as him. How old is Mia now?","36","num"),
("W05","word","A recipe for 4 people needs 300 g of flour. You cook for 10 people and have 650 g. How many grams are you short?","100","num"),
("W06","word","A phone plan costs 12 euros a month plus 0.05 euros for every MB above 2,000 MB. In March you use 2,740 MB. What is the bill in euros?","49","num"),
("W07","word","Three friends split a bill of 86 euros. Ben pays twice what Cai pays, and Ana pays 6 euros more than Ben. How many euros does Cai pay?","16","num"),
("L01","logic","Five runners finish a race. Dana finished before Eli but after Cleo. Ben finished last. Abe finished right after Dana. Who finished second?","Dana","word:abe,ben,cleo,dana,eli"),
("L02","logic","On an island, knights always tell the truth and knaves always lie. A says: \"B is a knave.\" B says: \"A and C are the same kind.\" What is C? Answer knight or knave.","knave","word:knight,knave"),
("L03","logic","Today is Wednesday. What day of the week is it 100 days from today?","Friday","word:monday,tuesday,wednesday,thursday,friday,saturday,sunday"),
("L04","logic","A drawer holds 6 red socks and 6 blue socks. In the dark, how many socks must you take out to be sure you have two red socks?","8","num"),
("L05","logic","Every member of a club plays chess or go. Nobody who plays go likes tea. Sam is a member and likes tea. Does Sam play chess? Answer yes, no or cannot tell.","yes","word:yes,no,cannot tell"),
("L06","logic","A clock shows 3:15. What is the smaller angle between the hour hand and the minute hand, in degrees?","7.5","num"),
("L07","logic","Anna, Bo and Cy each own one pet: a cat, a dog or a fish, all different. Anna does not own the dog. Bo owns neither the cat nor the dog. Who owns the dog?","Cy","word:anna,bo,cy"),
("C01","code",None,"4","num"),("C02","code",None,"66","num"),("C03","code",None,"4","num"),("C04","code",None,"55","num"),
("C05","code",None,"the","line"),("C06","code",None,"2 True","line"),
]
PUZZLES = [{"id": i, "kind": k, "user": (u if u else code_msg(i)), "accept": a, "mode": m} for i, k, u, a, m in P]
