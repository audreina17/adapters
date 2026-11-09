"""Matched streamed inference with allowlisted diagnostics; no credential/content logging."""
import json,time,uuid
from pathlib import Path
records=[]
def install(path=None):
 def save(row):
  row={**row,'time':time.time()};records.append(row)
  if path:
   p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
   with p.open('a') as f:f.write(json.dumps(row)+'\n')
 from streaming_transport import install as stream_install
 stream_install(save)
 from openai import OpenAI
 original_init=OpenAI.__init__
 def init(self,*args,**kwargs):
  original_init(self,*args,**kwargs)
  def request(req):
   req.extensions['_parity_start']=time.monotonic()
   req.extensions['_parity_id']=uuid.uuid4().hex
   save({'event':'http_attempt_start','attempt_id':req.extensions['_parity_id'],'retry_index':req.headers.get('x-stainless-retry-count'),'host':req.url.host})
  def response(resp):
   req=resp.request
   save({'event':'http_attempt_response','attempt_id':req.extensions.get('_parity_id'),'retry_index':req.headers.get('x-stainless-retry-count'),'status':resp.status_code,'elapsed_to_headers_seconds':time.monotonic()-req.extensions.get('_parity_start',time.monotonic()),'cf_ray':resp.headers.get('cf-ray'),'request_id':resp.headers.get('x-request-id'),'retry_after':resp.headers.get('retry-after')})
  self._client.event_hooks['request'].append(request)
  self._client.event_hooks['response'].append(response)
  save({'event':'client_config','max_retries':self.max_retries,'read_timeout_seconds':getattr(self.timeout,"read",self.timeout)})
 OpenAI.__init__=init
 from openai.resources.chat.completions import Completions
 original=Completions.create
 def wrapped(self,*args,**kwargs):
  start=time.monotonic()
  try:response=original(self,*args,**kwargs)
  except Exception as exc:
   save({'event':'error','elapsed_seconds':time.monotonic()-start,'error_type':type(exc).__name__,'http_status':getattr(exc,'status_code',None),'request_id':getattr(exc,'request_id',None),'model':kwargs.get('model'),'max_tokens':kwargs.get('max_tokens')});raise
  choice=response.choices[0];m=choice.message;extra=m.model_extra or {}
  save({'event':'response','elapsed_seconds':time.monotonic()-start,'model':kwargs.get('model'),'max_tokens':kwargs.get('max_tokens'),'finish_reason':choice.finish_reason,'content_chars':len(m.content or ''),'usage':response.usage.model_dump() if response.usage else None,'reasoning_chars':{k:len(v) for k,v in extra.items() if 'reason' in k and isinstance(v,str)}})
  return response
 Completions.create=wrapped
