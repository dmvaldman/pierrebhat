from datasets import load_dataset
from Issue2PR import Issue2PR
import requests
import json
from unidiff import PatchSet
import regex as re
import difflib

dataset = load_dataset("princeton-nlp/SWE-bench")
dataset_dev = dataset['dev']

config = {
    "snippet_type": "snippet",
    "write_code": "agent",
}

results = []

def check_language(repo_name, language):
    url = f"https://api.github.com/repos/{repo_name}/languages"
    response = requests.get(url)
    if response.status_code == 200:
        languages = response.json()
        # check if language is in top 2 languages by bytes
        top_languages = sorted(languages, key=languages.get, reverse=True)[:2]
        return (language in top_languages)
    else:
        raise Exception("Error getting file from GitHub")

_no_eol = "\ No newline at end of file"
_hdr_pat = re.compile("^@@ -(\d+),?(\d+)? \+(\d+),?(\d+)? @@$")

def make_patch(a,b):
  """
  Get unified string diff between two strings. Trims top two lines.
  Returns empty string if strings are identical.
  """
  diffs = difflib.unified_diff(a.splitlines(True),b.splitlines(True),n=0)
  try: _,_ = next(diffs),next(diffs)
  except StopIteration: pass
  # diffs = list(diffs); print(diffs)
  return ''.join([d if d[-1] == '\n' else d+'\n'+_no_eol+'\n' for d in diffs])

def apply_patch(s, patch, revert=False):
    """
    Apply patch to string s to recover newer string.
    If revert is True, treat s as the newer string, recover older string.
    """
    s = s.splitlines(True)
    p = patch.splitlines(True)
    t = ''
    i = sl = 0
    (midx,sign) = (1,'+') if not revert else (3,'-')
    while i < len(p) and p[i].startswith(("---","+++")): i += 1 # skip header lines
    while i < len(p):
        m = _hdr_pat.match(p[i])
        if not m: raise Exception("Bad patch -- regex mismatch [line "+str(i)+"]")
        l = int(m.group(midx))-1 + (m.group(midx+1) == '0')
        if sl > l or l > len(s):
            raise Exception("Bad patch -- bad line num [line "+str(i)+"]")
        t += ''.join(s[sl:l])
        sl = l
        i += 1
        while i < len(p) and p[i][0] != '@':
            if i+1 < len(p) and p[i+1][0] == '\\': line = p[i][:-1]; i += 2
            else: line = p[i]; i += 1
            if len(line) > 0:
                if line[0] == sign or line[0] == ' ': t += line[1:]
                sl += (line[0] != sign)
    t += ''.join(s[sl:])
    return t

def compare(patch, pr):
    patch_obj = PatchSet(patch)
    patch_added = patch_obj.added_files
    patch_modified = patch_obj.modified_files
    patch_removed = patch_obj.removed_files

    print(pr.diff_str, str(patch_obj))

    for patch in patch_modified:
        patch_str = str(patch)
        filename = patch.path
        # search for matching original file

        # original_file = pr.original_files[filename]
        # new_file = pr.new_files[filename]

        # patch_new_file = apply_patch(original_file, patch_str)
        # print(patch_new_file == new_file)



for datum in dataset_dev:
    repo_name = datum['repo']
    commit_sha = datum['base_commit']
    issue_description = datum['problem_statement']
    issue_title, issue_body = issue_description.split('\n', 1)

    fail_to_pass = json.loads(datum['FAIL_TO_PASS'])
    pass_to_pass = json.loads(datum['PASS_TO_PASS'])
    patch = datum['patch']
    test_patch = datum['test_patch']
    comments_text = datum['hints_text']

    if not check_language(repo_name, 'Python'):
        continue

    repo = Issue2PR.create_repo(repo_name)
    issue = Issue2PR.create_issue(issue_title, issue_body, repo_name)

    issue2PR = Issue2PR(repo=repo, issue=issue, options=config)
    pr = issue2PR.resolve()

    result = {
        "issue": issue.to_json(),
        "pr": pr.to_json(),
        "config": config,
        "log_file": issue2PR.logfile_path,
        "num_tokens": issue2PR.calc_num_tokens()
    }

    # compare against patch
    compare(patch, pr)

    results.append(result)

    save_path = f'issue2pr/data/swe.json'
    with open(save_path, 'w') as f:
        json.dump(results, f, indent=2)

print('hi')