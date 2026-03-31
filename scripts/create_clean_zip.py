import os
import zipfile

exclude_dirs = {'.venv', '.venv310', '.git', '.idea', '__pycache__'}
zip_name = 'ai-resume-builder-clean.zip'

if os.path.exists(zip_name):
    os.remove(zip_name)

with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk('.'):
        rel_root = os.path.relpath(root, '.')
        parts = rel_root.split(os.sep) if rel_root != '.' else []
        if parts and parts[0] in exclude_dirs:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for f in files:
            if f.endswith(('.pyc', '.pyo', '.pyd')) or f.endswith('.zip'):
                continue
            full = os.path.join(root, f)
            arc = os.path.normpath(os.path.relpath(full, '.'))
            z.write(full, arcname=arc)

print('CLEAN_ZIP_CREATED')
