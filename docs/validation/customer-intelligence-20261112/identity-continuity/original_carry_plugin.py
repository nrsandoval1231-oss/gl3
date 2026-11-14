"""Controlled comparison: restore only the original identity carry block in memory."""
import hashlib
import inspect
from pathlib import Path

def pytest_configure(config):
    import gridlens.intelligence.buying_chain as module
    source = inspect.getsource(module.enrich_buying_chain)
    start = source.index('        # Continue an existing project-local company identity')
    end = source.index('        current_claim_ids.append(str(new_claim.id))', start)
    original = Path(__file__).with_name('original-carry.txt').read_text()
    print('OVERLAY original55-line-carry SHA256',hashlib.sha256(original.encode()).hexdigest())
    print('OVERLAY replaced-candidate-carry SHA256',hashlib.sha256(source[start:end].encode()).hexdigest())
    rewritten = source[:start] + original + source[end:]
    exec(compile(rewritten, '<original-identity-carry-only-overlay>', 'exec'), module.__dict__)
