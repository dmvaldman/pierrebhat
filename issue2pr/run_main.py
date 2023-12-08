import json
from chat_compare_code import ChatCompareCode
from Issue2PR import Issue2PR
from issue import Issue, ResolvedIssue


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
                "pr": pr.to_json(),
                "config": config,
                "log_file": issue2PR.logfile_path,
                "num_tokens": issue2PR.calc_num_tokens()
            }

            results.append(result)

            # save results to file
            if save:
                config_str = Issue2PR.config_to_str(config)
                # refactor files to be [{filename, content}, ...]
                # add token content length
                with open(f'issue2pr/data/{issue2PR.logfile_path}.json', 'w') as f:
                    json.dump(results, f, indent=2)

    return results

def test(config_str):
    test_results = []

    config = Issue2PR.str_to_config(config_str)

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
        "snippet_type": "snippet",
        "write_code": "agent",
    }

    with open(os.path.join('data', 'datasets', 'repo_issues.json')) as json_file:
        issues_dataset = json.load(json_file)

    pr_results = main(issues_dataset, config)

    # test
    config_str = Issue2PR.config_to_str(config)
    test(config_str)
