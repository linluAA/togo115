# 前端源码结构

运行时仍加载 `app/static/app.js` 和 `app/static/styles.css`，这两个文件由源码分片生成。

修改规则：

- JS 逻辑改 `app/static/src/js/*.js`
- CSS 样式改 `app/static/src/css/*.css`
- 修改后执行：`python app/tools/build_static.py`
- 不要直接长期维护 `app/static/app.js` 和 `app/static/styles.css`

这样保留无前端构建依赖的部署方式，同时避免继续维护单个超大前端文件。
