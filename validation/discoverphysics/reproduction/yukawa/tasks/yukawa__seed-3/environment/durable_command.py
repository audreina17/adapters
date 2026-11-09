import sys,pathlib,subprocess,json,os
folder=pathlib.Path(sys.argv[2])
if sys.argv[1]=='read':
 p=folder/'result.json'
 if p.exists():print(p.read_text())
 else:sys.exit(3)
else:
 try:folder.mkdir()
 except FileExistsError:sys.exit(0)
 try:
  p=subprocess.run(sys.argv[3],shell=True,capture_output=True,text=True,timeout=3900)
  d={'return_code':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
 except Exception as e:d={'return_code':1,'stdout':'','stderr':type(e).__name__}
 t=folder/'result.tmp';t.write_text(json.dumps(d));t.replace(folder/'result.json')
