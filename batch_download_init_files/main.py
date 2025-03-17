import os
import requests

def get_repo_tags(owner, repo):
    """
    获取指定仓库的所有标签（tags）
    """
    url = f'https://api.github.com/repos/{owner}/{repo}/tags'
    response = requests.get(url)
    if response.status_code == 200:
        json_data = response.json()
        tags = []
        for tag in json_data:
            tags.append(tag['name'])
        return tags
    else:
        print(f"无法获取标签列表，状态码：{response.status_code}")
        return []

def download_init_file(owner, repo, tag, file_path, save_dir):
    """
    下载指定tag的__init__.py文件
    """
    raw_url = f'https://raw.githubusercontent.com/{owner}/{repo}/{tag}/{file_path}'
    response = requests.get(raw_url)
    if response.status_code == 200:
        # 创建保存目录
        tag_dir = os.path.join(save_dir, tag)
        os.makedirs(tag_dir, exist_ok=True)
        # 保存文件
        file_name = os.path.basename(file_path)
        save_path = os.path.join(tag_dir, file_name)
        with open(save_path, 'wb') as f:
            f.write(response.content)
        print(f"已下载 {tag} 的 {file_path}")
    else:
        print(f"无法下载 {tag} 的 {file_path}，状态码：{response.status_code}")

def batch_download(owner, repo, file_path, save_dir):
    # 获取所有tags
    tags = get_repo_tags(owner, repo)
    if not tags:
        print("没有可用的标签，程序结束。")
        return
    # 下载每个tag的__init__.py文件
    for tag in tags:
        download_init_file(owner, repo, tag, file_path, save_dir)

if __name__ == "__main__":
    # 仓库信息
    owner = 'pallets'  # 替换为实际的仓库所有者用户名
    repo = 'flask'         # 替换为实际的仓库名称
    file_path = 'src/flask/__init__.py'  # 文件在仓库中的路径
    save_dir = f'./downloaded_files/{repo}'  # 本地保存目录

    batch_download(owner, repo, file_path, save_dir)