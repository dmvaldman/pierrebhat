import json
from chat_write_code import SNIPPET_TYPE, GET_CONTENT_TYPE
from chat_compare_code import ChatCompareCode
from Issue2PR import Issue2PR, WRITE_CODE_TYPE
from issue import Issue, ResolvedIssue
import os
import time

def main(issues_dataset=None, config=None, save=True, save_path=''):
    results = {}
    issue2PR = Issue2PR(options=config)

    for repo_name, issues in issues_dataset.items():
        if repo_name in ['wncc/UniTrain', 'espin086/GPT-Jobhunter', 'Clueless-Community/scrape-up', 'Ebazhanov/linkedin-skill-assessments-quizzes']:
            continue

        # temp hack to only run one repo
        if repo_name != 'roboflow/supervision':
            continue

        repo = Issue2PR.create_repo(repo_name)
        issue2PR.set_repo(repo)

        for issue in issues:
            sha = issue['pr']['base_sha']
            repo.checkout(sha)

            issue = Issue2PR.create_issue(issue['title'], issue['body'], repo_name, num=issue['num'], sha=sha)
            issue2PR.set_issue(issue)

            pr = issue2PR.resolve()

            result = {
                "issue": issue.to_json(),
                "pr": pr.to_json(),
                "config": config,
                "log_file": issue2PR.logfile_path,
                "num_tokens": issue2PR.calc_num_tokens()
            }

            key = f"{repo_name}_{issue.num}"
            results[key] = result

            # save results to file (load and update)
            if save:
                # if save_path exists, update
                if os.path.exists(save_path):
                    with open(save_path, 'r') as f:
                        saved_results = json.load(f)
                else:
                    saved_results = {}
                saved_results.update(results)
                with open(save_path, 'w') as f:
                    json.dump(saved_results, f, indent=2)

    return results

def test(results_path):
    with open(results_path, 'r') as f:
        pr_results = json.load(f)

    test_results = {}

    response = {
        "attempts": 0,
        "correct": 0,
        "config": config
    }

    for key, pr_result in pr_results.items():
        issue_data = pr_result['issue']

        issue = ResolvedIssue(**issue_data)
        pr_info = issue.fetch_pr_info()
        issue.set_pr_info(pr_info)

        proposed_files = pr_result['pr']['new_files']
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

        test_results[key] = test_result

        response['attempts'] += 1
        if is_solution_correct:
            response['correct'] += 1

        response['results'] = test_results

        # save results to file
        # save_path is results_path with 'check_' post_pended
        save_path = results_path.replace('.json', '_check.json')
        with open(save_path, 'w') as f:
            response['results'] = pr_results
            json.dump(response, f, indent=2)

if __name__ == "__main__":
    config = {
        "snippet_type": SNIPPET_TYPE.SNIPPET.value,
        "get_content_type": GET_CONTENT_TYPE.CONTEXT.value,
        "write_code": WRITE_CODE_TYPE.AGENT.value,
        "use_plan": False
    }

    dataset_path = os.path.join('data', 'datasets', 'repo_issues.json')
    date = time.strftime("%Y-%m-%d") # date in format 'YYYY-MM-DD'
    config_str = '_'.join([f"{key}={value}" for key, value in config.items()])
    save_path = f'issue2pr/data/{date}_{config_str}.json'

    with open(dataset_path) as json_file:
        issues_dataset = json.load(json_file)

    pr_results = main(issues_dataset, config, save=True, save_path=save_path)

    test(save_path)
