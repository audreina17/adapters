from openai.types.chat import ChatCompletion
import time
from stream_structure import observe
_emit = lambda row: None


def assemble(chunks):
    start = last = time.monotonic()
    count = 0
    max_gap = 0.0
    first = None
    metadata = None
    content = []
    reasoning = {}
    saw_content = False
    finish_reason = None
    usage = None
    for chunk in chunks:
        now = time.monotonic()
        count += 1
        first = now - start if first is None else first
        max_gap = max(max_gap, now - last)
        last = now
        if count == 1 or now - start > 0 and count % 1000 == 0:
            _emit({"event":"stream_progress","chunks":count,"first_chunk_seconds":first,"max_chunk_gap_seconds":max_gap})
        if metadata is None:
            metadata = {'id': chunk.id, 'created': chunk.created, 'model': chunk.model}
        if chunk.usage is not None:
            usage = chunk.usage.model_dump()
        for choice in chunk.choices:
            if choice.index != 0:
                raise ValueError('Benchmark transport supports one completion only')
            if choice.delta.tool_calls or choice.delta.function_call:
                raise ValueError('Unexpected tool call in text-only benchmark')
            if choice.delta.content is not None:
                saw_content = True
                content.append(choice.delta.content)
            for key, value in (choice.delta.model_extra or {}).items():
                if 'reason' in key and isinstance(value, str):
                    reasoning.setdefault(key, []).append(value)
            if choice.finish_reason is not None:
                finish_reason = choice.finish_reason
    _emit({"event":"stream_end","chunks":count,"first_chunk_seconds":first,"max_chunk_gap_seconds":max_gap,"elapsed_seconds":time.monotonic()-start,"finish_reason":finish_reason})
    if metadata is None or finish_reason is None:
        raise RuntimeError('Incomplete inference stream; no terminal finish reason')
    return ChatCompletion.model_validate({
        **metadata, 'object': 'chat.completion', 'usage': usage,
        'choices': [{'index': 0, 'finish_reason': finish_reason, 'logprobs': None,
                     'message': {'role': 'assistant', 'content': ''.join(content) if saw_content else None,
                                 **{key: ''.join(value) for key, value in reasoning.items()}}}],
    })


def install(emit=None):
    global _emit
    if emit is not None: _emit = emit
    from openai.resources.chat.completions import Completions
    original = Completions.create
    if getattr(original, '_benchmark_streaming_transport', False):
        return

    def create(self, *args, **kwargs):
        if kwargs.get('stream'):
            return original(self, *args, **kwargs)
        options = dict(kwargs)
        options['stream'] = True
        options['stream_options'] = {**(options.get('stream_options') or {}), 'include_usage': True}
        with original(self, *args, **options) as stream:
            observer = observe(stream, _emit)
            try:
                return assemble(stream)
            finally:
                observer.publish()

    create._benchmark_streaming_transport = True
    Completions.create = create
