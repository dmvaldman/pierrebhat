from bot import PRBot, SubmittedPR
from repo import Repo

from dotenv import load_dotenv
load_dotenv()

if __name__ == "__main__":
    repo_org_src = 'karpathy/nanoGPT'
    repo_org_tgt = 'pierrebhat/nanoGPT'

    issue_num = 50
    num_hits = 5

    bot = PRBot(repo_org_tgt)
    repo = Repo(repo_org_src)

    issues_all = repo.get_issue_list()
    issue = [issue for issue in issues_all if issue.num == issue_num][0]
    files = repo.get_nearest_files(issue, num_hits=num_hits)
    changes = bot.generate_patches(files, issue)

    pr = SubmittedPR(issue, changes)
    bot.create_pr(pr)