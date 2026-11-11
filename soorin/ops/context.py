"""Read-only, evidence-aware native context query; does not run response actions."""
import argparse,json,os,uuid
from soorin.adapters.utopia.knowledge_client import KnowledgeClient
from soorin.contracts.grounded_context import extractive_answer

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kb',required=True);p.add_argument('--tenant',required=True);p.add_argument('--entity',required=True)
    p.add_argument('--base-url',default='http://127.0.0.1:2516');p.add_argument('--at');p.add_argument('--as-of');p.add_argument('--extractive',action='store_true')
    a=p.parse_args();uuid.UUID(a.kb)
    token=os.environ.get('UTOPIA_SESSION_TOKEN','')
    if not token:p.error('UTOPIA_SESSION_TOKEN is required')
    context=KnowledgeClient(a.base_url,session_token=token).context(a.kb,tenant_id=a.tenant,entity=a.entity,at=a.at,as_of=a.as_of)
    print(json.dumps(extractive_answer(context) if a.extractive else context,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
