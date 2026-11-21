"""Reject skipped, missing or failed E01–E12 cases; a green empty suite is not G0."""
import argparse
import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET


def check(path,profile):
    root=ET.parse(path).getroot();cases=list(root.iter('testcase'))
    profiles=['desktop','mobile'] if profile=='all' else [profile]
    expected={(f'E{i:02d}',p) for i in range(1,13) for p in profiles}
    actual=[]
    for case in cases:
        match=re.fullmatch(r'test_(E\d{2})_.+\[(desktop|mobile)\]',case.attrib.get('name',''))
        if not match:raise ValueError('Unexpected E2E testcase: '+case.attrib.get('name',''))
        if any(case.find(tag) is not None for tag in ('failure','error','skipped')):raise ValueError('Failed, errored or skipped case: '+case.attrib['name'])
        actual.append((match[1],match[2]))
    if len(actual)!=len(expected) or set(actual)!=expected:raise ValueError('E01–E12 coverage is incomplete or duplicated')
    return {'passed':True,'profile':profile,'tests':len(actual),'skipped':0,'cases':[f'{case}/{p}' for case,p in sorted(actual)]}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('junit');parser.add_argument('--profile',choices=['all','desktop','mobile'],required=True);parser.add_argument('--output')
    args=parser.parse_args()
    try:result=check(args.junit,args.profile)
    except (ValueError,ET.ParseError,OSError) as exc:parser.exit(1,'E2E gate rejected: '+str(exc)+'\n')
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output:
        target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text,encoding='utf8')
    print(text)


if __name__=='__main__':main()
