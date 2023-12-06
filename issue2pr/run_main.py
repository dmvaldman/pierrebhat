import json
import time
from contextlib import redirect_stdout
from chat_compare_code import ChatCompareCode
from Issue2PR import Issue2PR, Issue, ResolvedIssue

def config_to_str(config):
    config_str = ''
    for key, val in config.items():
        config_str += f'{key}_{val}_'
    return config_str

def str_to_config(str):
    keyvals = str.split('_')[1:-1]
    config = {}
    for index in range(len(keyvals, 2)):
        key, val = keyvals[index], keyvals[index + 1]
        config[key] = val
    return config

def main(issues_dataset=None, config=None, save=True):
    results = []
    issue2PR = Issue2PR(options=config)

    for repo_name, issues in issues_dataset.items():
        if repo_name in ['wncc/UniTrain', 'espin086/GPT-Jobhunter', 'Clueless-Community/scrape-up', 'Ebazhanov/linkedin-skill-assessments-quizzes']:
            continue

        repo = Issue2PR.create_repo(repo_name)
        issue2PR.set_repo(repo)

        for issue in issues:
            sha = issue['pr']['base_sha']
            repo.checkout(sha)

            issue = Issue2PR.create_issue(issue['title'], issue['body'], repo_name)
            issue2PR.set_issue(issue)

            pr = issue2PR.resolve()

            result = {
                "issue": issue.to_json(),
                "pr": pr.to_json()
            }

            results.append(result)

            # save results to file
            if save:
                config_str = config_to_str(config)
                with open(f'data/prs_{config_str}.json', 'w') as f:
                    json.dump(results, f, indent=2)

    return results

def test(config_str):
    test_results = []

    config = str_to_config(config_str)

    with open(f'data/prs_{config_str}.json', 'w') as f:
        pr_results = json.load(f)

    response = {
        "attempts": 0,
        "correct": 0,
        "config": config
    }

    for pr_result in pr_results:
        issue_data = pr_result['issue']

        issue = ResolvedIssue(**issue_data)
        pr_info = issue.fetch_pr_info()
        issue.set_pr_info(pr_info)

        proposed_files = pr_result['pr']['files']
        actual_files = issue.get_changed_file_contents()

        proposed_filenames = list(proposed_files.keys())
        actual_filenames = list(actual_files.keys())

        chat_compare_code = ChatCompareCode(issue, proposed_files, actual_files)
        chat_compare_code.initiate_chat(silent=False)

        is_solution_correct = chat_compare_code.result.result()
        reason = chat_compare_code.reason.result()

        test_result = pr_result.copy()

        test_result['pr'].update({
            "actual_filenames": list(actual_files.keys()),
            "is_filenames_correct": set(actual_filenames) <= set(proposed_filenames),
            "is_pr_correct": is_solution_correct,
            "correct_pr_reason": reason
        })

        test_results.append(test_result)

        response['attempts'] += 1
        if is_solution_correct:
            response['correct'] += 1

        response['results'] = pr_results

        # save results to file
        with open(f'data/prs_test_{config_str}.json', 'w') as f:
            response['results'] = pr_results
            json.dump(response, f, indent=2)

if __name__ == "__main__":
    import os

    config = {
        "ts": time.strftime("%Y%m%d-%H%M"),
        "snippet_type": "snippet",
        "write_code": "agent"
    }

    curr_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(curr_dir, 'logs', config_to_str(config) + '.txt')

    with open(os.path.join('data', 'datasets', 'repo_issues.json')) as json_file:
        issues_dataset = json.load(json_file)

    print("Outputting to", output_path)

    with open(output_path, 'w') as file:
        with redirect_stdout(file):
            pr_results = main(issues_dataset, config)

    # test
    config_str = config_to_str
    test(config_str)
