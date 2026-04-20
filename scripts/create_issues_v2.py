import requests
import os
import json

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
USERNAME = "SaJaToGu"

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json"
}

def get_repos():
    url = f"https://api.github.com/users/{USERNAME}/repos"
    response = requests.get(url, headers=HEADERS)
    return response.json()

def create_issue(repo_name, title, body):
    url = f"https://api.github.com/repos/{USERNAME}/{repo_name}/issues"
    
    data = {
        "title": title,
        "body": body
    }

    response = requests.post(url, headers=HEADERS, json=data)
    
    if response.status_code == 201:
        print(f"Issue erstellt in {repo_name}: {title}")
    else:
        print(f"Fehler bei {repo_name}: {response.text}")

def main():
    repos = get_repos()

    for repo in repos:
        repo_name = repo["name"]

        # Beispiel Checks
        if not repo["description"]:
            create_issue(
                repo_name,
                "Add repository description",
                "This repository has no description. Add a meaningful description."
            )

        if not repo["topics"]:
            create_issue(
                repo_name,
                "Add repository topics",
                "This repository has no topics. Add relevant topics for discoverability."
            )

if __name__ == "__main__":
    main()
