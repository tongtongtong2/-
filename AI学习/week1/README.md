# 第1周：LLM核心概念（Transformer / Token / Embedding）

## 本周目标
能用自己的话解释：Token是什么、Embedding是什么、Attention在干嘛、Transformer怎么工作。
不要求手写代码实现，但要求概念清晰。

---

## Day 1（周一）：Tokenization

### 看
3Blue1Brown "直观理解Transformer" 前10分钟（讲Tokenization那段）
https://www.youtube.com/watch?v=wjZofJX0v4M （B站有搬运）

### 读
Jay Alammar "The Illustrated Transformer" — 只看开头tokenization部分
https://jalammar.github.io/illustrated-transformer/

### 写
运行 `python week1/01_tokenization.py`
- 看看中文/英文/代码是怎么切成token的
- 同一个意思中英文token数差多少
- 改几个例子试

---

## Day 2（周二）：Embedding

### 看
3Blue1Brown "直观理解Transformer" 继续看Embedding部分

### 读
Jay Alammar "The Illustrated GPT2" — Embedding部分
https://jalammar.github.io/illustrated-gpt2/

### 写
运行 `python week1/02_embedding.py`
- 理解向量是什么
- 计算句子的相似度
- 感受"语义近=向量近"

---

## Day 3（周三）：Attention机制

### 看
3Blue1Brown "直观理解Transformer" 后半段（Attention核心）
这是整个视频最精彩的部分，反复看

### 读
Lilian Weng "Attention? Attention!"
https://lilianweng.github.io/posts/2018-06-24-attention/

### 写
不用写代码。拿纸笔画图：
- 画出Q、K、V三个矩阵
- 画出"Q×K^T → softmax → ×V"的流程
- 用自己的话写出：Attention到底在算什么？

---

## Day 4（周四）：Transformer全貌

### 看
李宏毅 "Transformer" （B站搜，2021年或2024年版本都可以）
约1小时，讲得很细

### 读
Jay Alammar "The Illustrated Transformer" 完整读一遍

### 写
输出一份"给同事讲的5分钟Transformer科普"
- Token → Embedding → Attention → FFN → 输出
- 不超过500字
- 写完后读出来，卡住的地方就是没真懂的地方

---

## Day 5（周五）：动手复习 + GPT工作原理

### 看
Andrej Karpathy "Let's build GPT from scratch" 前半段（约1小时）
https://www.youtube.com/watch?v=kCc8FmEb1nY

### 写
运行之前两天的代码，改参数看效果：
- 01_tokenization.py：换不同的文本，观察token数量
- 02_embedding.py：换不同的句子对，观察相似度变化

---

## 周六：Karpathy视频看完

### 看
Andrej Karpathy "Let's build GPT from scratch" 后半段

### 写
跟着karpathy的notebook跑一遍（不强求每一行都懂）
https://github.com/karpathy/nanoGPT
看看一个最小GPT是怎么训练出来的

---

## 周日：本周检查

完成以下自测（口头回答即可）：

- [ ] 什么是Token？为什么中文比英文费token？
- [ ] Embedding做了什么？为什么相似的词Embedding向量接近？
- [ ] Self-Attention的Q、K、V分别代表什么？
- [ ] Transformer的Encoder和Decoder有什么区别？
- [ ] GPT系列用了Transformer的哪一部分？为什么？

---

## 本周代码

在 `week1/` 目录下有两个练习脚本，按天数运行。

### 环境准备

```bash
# 确保你在 D:\project\AI学习 目录下
cd "D:\project\AI学习"

# 创建虚拟环境
python -m venv venv

# 激活（Windows git-bash）
source venv/Scripts/activate

# 安装依赖
pip install openai tiktoken numpy
```
