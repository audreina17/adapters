import hashlib
import json
from types import MethodType
import httpx

KNOWN_FIELDS = frozenset(('role','content','reasoning','reasoning_content','reasoning_details','tool_calls','function_call','refusal','audio','text'))
KNOWN_FINISHES = frozenset(('stop','length','tool_calls','function_call','content_filter'))

def field_label(key):
    if key in KNOWN_FIELDS:
        return key
    return 'unknown_sha256:' + hashlib.sha256(key.encode()).hexdigest()

class Observer:
    def __init__(self, stream, emit):
        self.emit = emit
        self.published = False
        self.state = dict(event='stream_structure', schema_version=1,
            sse_events=0, done_exact=0, done_prefix=0, clean_eof=False,
            read_error=False, iterator_error_type=None, malformed_json=0,
            finish_reasons={}, delta_fields={}, content_chars_before_done=0,
            reasoning_chars_before_done=0, events_after_done=0)
        original = stream._iter_events
        observer = self
        def events(_stream):
            try:
                for event in original():
                    # Observation must never change SDK decoding or error behavior.
                    try:
                        observer.record(event)
                    except Exception:
                        observer.state['observation_error'] = True
                    yield event
                observer.state['clean_eof'] = True
            except BaseException as exc:
                observer.state['iterator_error_type'] = type(exc).__name__
                observer.state['read_error'] = isinstance(exc, httpx.TransportError)
                raise
        stream._iter_events = MethodType(events, stream)

    def record(self, event):
        s = self.state
        s['sse_events'] += 1
        data = event.data
        if data.startswith('[DONE]'):
            s['done_prefix'] += 1
            s['done_exact'] += int(data == '[DONE]')
            return
        after_done = bool(s['done_prefix'])
        s['events_after_done'] += int(after_done)
        try:
            row = json.loads(data)
        except (ValueError, TypeError):
            s['malformed_json'] += 1
            return
        if not isinstance(row, dict):
            return
        for choice in row.get('choices', []) or []:
            if not isinstance(choice, dict):
                continue
            finish = choice.get('finish_reason')
            if finish is not None:
                label = finish if isinstance(finish,str) and finish in KNOWN_FINISHES else 'other'
                s['finish_reasons'][label] = s['finish_reasons'].get(label,0)+1
            delta = choice.get('delta')
            if not isinstance(delta,dict):
                continue
            for key,value in delta.items():
                label = field_label(key)
                stats = s['delta_fields'].setdefault(label,dict(occurrences=0,string_chars=0,types={}))
                stats['occurrences'] += 1
                kind = type(value).__name__
                stats['types'][kind] = stats['types'].get(kind,0)+1
                if isinstance(value,str):
                    stats['string_chars'] += len(value)
                    if not after_done:
                        if key == 'content': s['content_chars_before_done'] += len(value)
                        if 'reason' in key: s['reasoning_chars_before_done'] += len(value)

    def publish(self):
        if not self.published:
            self.published = True
            try:
                self.emit(self.state)
            except Exception:
                pass

def observe(stream, emit):
    return Observer(stream, emit)
