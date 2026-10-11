import json
done=set()
for l in open('<lab>/shutdown2/shutdown-replica-trials.jsonl'):
    if l.strip(): r=json.loads(l); done.add((r['arm'],r['trial_index']))
left=[(a,i) for i in range(12) for a in ('J','K') if (a+'_on',i) not in done]
print(len(left))
