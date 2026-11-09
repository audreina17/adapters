import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import time

from metadata_hook import install
install('/evidence/inference-metadata.jsonl')
os.chdir('/opt/discoverphysics')
sys.path.insert(0,'/opt/discoverphysics/ScienceAgent')
from scienceagent import llm_client
llm_client.HTTP_TIMEOUT_S=3600.0
# Provider configuration only: preserve the pinned judge prompt, rubric and parser.
from scienceagent import evaluator
class GlmBudgetedExplanationJudge(evaluator.ExplanationJudge):
    def __init__(self, judge_model="claude-opus-4-6", max_tokens=65536):
        super().__init__(judge_model=judge_model, max_tokens=max_tokens)
evaluator.ExplanationJudge = GlmBudgetedExplanationJudge
original=llm_client.complete
out=Path('/evidence');out.mkdir(exist_ok=True)
def logged_complete(*args,**kwargs):
    with (out/'model-calls.jsonl').open('a') as f:
        f.write(json.dumps({'event':'request','time':time.time(),'args':args,'kwargs':kwargs})+'\n')
    value=original(*args,**kwargs)
    with (out/'model-calls.jsonl').open('a') as f:
        f.write(json.dumps({'event':'response','time':time.time(),'text':value})+'\n')
    return value
llm_client.complete=logged_complete
try:
    runpy.run_path('/opt/discoverphysics/ScienceAgent/run_discovery.py',run_name='__main__')
finally:
    trajectories=Path('/opt/discoverphysics/results/trajectories')
    if trajectories.exists():shutil.copytree(trajectories,out/'trajectories',dirs_exist_ok=True)
