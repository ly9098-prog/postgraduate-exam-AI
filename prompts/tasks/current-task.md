请把当前小程序项目中的所有 Lottie 动画资源统一迁移到分包中，目标是彻底减少主包体积（当前主包已接近/超过 1.5MB 限制）。

### 🎯 目标

- 所有 Lottie JSON / JS 动画文件 **必须从主包移除**
- 统一放入独立分包：`subpackages/animation/`
- 保证现有功能调用不受影响（路径/引用必须同步修改）

------

### 📦 分包结构要求

请创建或使用如下结构：

```
subpackages/
  animation/
    lottie/
      xxx.json (如果仍需保留)
      xxx.js   (如已转换则保留js)
```

------

### 🔧 需要完成的修改

1. **迁移资源**
   - 将 `assets/lottie/` 下所有文件移动到 `subpackages/animation/lottie/`
2. **修改引用路径**
   - 所有 `import / require / path` 指向 Lottie 的地方统一更新为分包路径
   - 确保 lottie.loadAnimation 的 path 或 animationData 正确
3. **检查构建依赖**
   - 确认没有任何 Lottie 文件仍被主包引用
   - 确保不会被 webpack/miniprogram build 再次打入主包
4. **验证主包体积优化**
   - 输出迁移前后主包体积变化说明
   - 确保 Lottie 不再出现在主包 bundle 中

------

### ⚠️ 强约束

- ❌ 不允许只是“改路径但文件仍在主包”
- ❌ 不允许复制一份保留在 assets
- ❌ 不允许运行时仍从主包引用 JSON
- ✔ 必须通过分包加载实现隔离

------

### 🧠 补充要求（重要）

- 如果发现 Lottie 被多个页面使用，请统一抽象成一个分包内的 loader 工具
- 如果存在 JS 内联 JSON（animationData），也必须一起移动到分包
- 如果支持懒加载，请优先改为分包按需加载

------

### 🎯 最终目标

主包中 **完全不包含任何 Lottie JSON / JS 动画资源**

