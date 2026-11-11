"""Authenticated native settings bootstrap and synthetic local CPU smoke tests."""
import argparse
import json
import math
import os
import time
import urllib.parse
import urllib.request
import uuid
from soorin.e2e.local_validation import _request_json, select_isolated_api, NoRedirect
from soorin.services.cpu_models import MODELS


def smoke(role, base, *, request=None):
    url=urllib.parse.urlsplit(base)
    if url.scheme!='http' or url.hostname not in {'127.0.0.1','localhost','::1'} or url.port not in {8080,2811,2812,2813} or url.username or url.password or url.path or url.query or url.fragment:
        raise ValueError('model smoke accepts only an explicit local CPU service')
    def local(path, body=None):
        headers={'Content-Type':'application/json'}
        if os.environ.get('SOORIN_MODEL_API_KEY'):
            headers['Authorization']='Bearer '+os.environ['SOORIN_MODEL_API_KEY']
        data=None if body is None else json.dumps(body).encode()
        req=urllib.request.Request(base+path,data=data,headers=headers)
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=120) as response:
            return json.load(response)
    request=request or local
    started=time.perf_counter()
    ready=request('/ready')
    expected='@'.join(MODELS[role])
    if ready.get('ready') is not True or ready.get('model')!=expected:
        raise ValueError('model readiness/revision mismatch')
    if role=='embedding':
        body={'model':expected,'input':['Synthetic host observation','مشاهده میزبان آزمایشی']}
        first=request('/v1/embeddings',body)['data']
        second=request('/v1/embeddings',body)['data']
        vectors=[row['embedding'] for row in first]
        if len(vectors)!=2 or any(len(v)!=1024 or any(type(x) not in (int,float) or not math.isfinite(x) for x in v) for v in vectors):
            raise ValueError('invalid dense vectors')
        if any(abs(a-b)>1e-5 for x,y in zip(first,second) for a,b in zip(x['embedding'],y['embedding'])):
            raise ValueError('inference is not repeatable')
        result={'dimension':1024,'languages':['en','fa'],'repeatable':True}
    elif role=='reranker':
        rows=request('/rerank',{'model':expected,'query':'synthetic host login','texts':['Synthetic host login observed','Unrelated orchard harvest']})
        if len(rows)!=2 or {row.get('index') for row in rows}!={0,1} or any(not math.isfinite(row['score']) for row in rows):
            raise ValueError('invalid reranker scores')
        result={'candidate_count':2,'score_semantics':'uncalibrated relevance'}
    else:
        rows=request('/ner',{'model':expected,'text':'Synthetic malware contacted 192.0.2.10.'})
        if rows.get('review_required') is not True or not isinstance(rows.get('proposals'),list):
            raise ValueError('NER proposals must require review')
        result={'proposal_count':len(rows['proposals']),'review_required':True,'language':'en'}
    return {'status':'PASS','synthetic':True,'role':role,'model':expected,'elapsed_seconds':time.perf_counter()-started,**result}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    probe=sub.add_parser('smoke');probe.add_argument('--role',choices=MODELS,required=True);probe.add_argument('--base-url',required=True)
    config=sub.add_parser('configure');config.add_argument('--workspace',required=True);config.add_argument('--base-url',default='http://127.0.0.1:2516')
    for role in ('chat','embedding','reranker'):config.add_argument('--'+role,action='store_true')
    args=parser.parse_args()
    if args.command=='smoke':print(json.dumps(smoke(args.role,args.base_url)));return
    base=select_isolated_api(args.base_url);uuid.UUID(args.workspace)
    token=os.environ.get('UTOPIA_SESSION_TOKEN','')
    if not token:parser.error('UTOPIA_SESSION_TOKEN is required; use a workspace administrator session')
    if not any((args.chat,args.embedding,args.reranker)):parser.error('select at least one model role')
    path=f'/api/v1/workspaces/{args.workspace}/settings'
    if args.chat or args.embedding:
        current=_request_json(base,path,token=token)
        fields=('chat_base_url','chat_model','chat_reasoning_effort','embed_base_url','embed_model','embed_dim')
        body={k:current[k] for k in fields if k in current}
        if args.chat:
            key=os.environ.get('DEEPSEEK_API_KEY','')
            if not key:parser.error('DEEPSEEK_API_KEY is required for --chat')
            body.update(chat_base_url='https://api.deepseek.com',chat_model=os.environ.get('DEEPSEEK_MODEL','deepseek-flash'),chat_reasoning_effort='none',chat_api_key=key)
        if args.embedding:body.update(embed_base_url='http://embedding:8080/v1',embed_model='@'.join(MODELS['embedding']),embed_dim=1024)
        _request_json(base,path,token=token,method='PUT',body=body)
    if args.reranker:
        _request_json(base,path+'/reranker',token=token,method='PUT',body={'enabled':True,'base_url':'http://reranker:8080','model':'@'.join(MODELS['reranker']),'fallback':False})
    print(json.dumps({'status':'configured','workspace':args.workspace,'connectivity':'NOT RUN','secrets':'omitted'}))


if __name__=='__main__':main()
