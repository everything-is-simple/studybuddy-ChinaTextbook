# studybuddy-ChinaTextbook

小学生教材与基础性作业的**下载工作目录**。本仓库只版本化**下载脚本与清单**；真实教材/作业 PDF 只存本地（体积超 GitHub 限制），凭 token 重新运行脚本即可再生。

## 目录约定

```text
小学教材\<学段>\<年级>\<科目>\<出版社><科目><年级><上/下册>.pdf
    例：小学教材\小学五年级\语文\人教版语文五年级上册.pdf
基础性作业\<科目>\<科目>作业<年级><上/下册>.pdf
下载教材.py          从 TapXWorld/ChinaTextbook（GitHub raw 直链）下载教材 PDF，免登录
下载教材音频.py      从国家中小学智慧教育平台下载教材配套音频（需 token）
下载基础性作业.py    下载基础性作业 PDF
教材清单.md          已就位教材清单与缺口盘点
现成资源盘点.md      本地已有资源盘点
智慧教育token.txt    智慧教育平台登录 token（密钥，已 gitignore，永不入库）
```

## 使用

Python 3.10+，无第三方依赖（urllib 标准库）。本机配置了系统代理，脚本内已用 `ProxyHandler({})` 绕过。

```text
python 下载教材.py          # 按教材清单缺项下载
python 下载基础性作业.py
python 下载教材音频.py      # 读取 智慧教育token.txt
```

token 过期时：登录 basic.smartedu.cn 后从浏览器复制新 token 覆盖 `智慧教育token.txt`。

## 仓库边界

- **入库**：下载脚本、清单文档、本 README、.gitignore
- **不入库**：教材/作业 PDF、音频（本地保留，可由脚本再生）、token 等密钥
- 远端：https://github.com/everything-is-simple/studybuddy-ChinaTextbook
