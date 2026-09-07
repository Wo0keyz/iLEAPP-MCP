import os
import glob
import re
import json

artifact_files = glob.glob('scratch/iLEAPP_repo/scripts/artifacts/*.py')
print(f'Found {len(artifact_files)} artifact scripts in iLEAPP')

artifacts = []

for f in sorted(artifact_files):
    basename = os.path.basename(f)
    try:
        with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
            content = fp.read()
        
        # search for name
        names = re.findall(r'["\']name["\']\s*:\s*["\']([^"\']+)["\']', content)
        categories = re.findall(r'["\']category["\']\s*:\s*["\']([^"\']+)["\']', content)
        
        # search for data_headers
        data_headers_blocks = re.findall(r'data_headers\s*=\s*([(\[][^;\n]+[)\]])', content)
        
        for n in names:
            safe_name = n.replace('/', '_').replace('\\', '_')
            artifacts.append({
                'name': n,
                'safe_name': safe_name,
                'file': basename,
                'categories': categories,
            })
    except Exception as e:
        pass

with open('scratch/artifacts_dump.json', 'w', encoding='utf-8') as out:
    json.dump(artifacts, out, indent=2)

print(f'Successfully dumped {len(artifacts)} artifacts to scratch/artifacts_dump.json')
