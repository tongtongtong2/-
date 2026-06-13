"""
第1周 Day2-3 练习：Embedding
理解词向量是什么，语义相似度如何计算。

需要先设置 OPENAI_API_KEY 环境变量：
    export OPENAI_API_KEY="sk-..."

或者修改下面 API_KEY 变量。

如果没有API key，可以用本地模型替代方案（见文件末尾）。

运行: python 02_embedding.py
"""

import os
import numpy as np

# ============================================================
# 方式A：OpenAI API（推荐，最准确）
# ============================================================

API_KEY = os.environ.get("OPENAI_API_KEY", "")

def cosine_similarity(a, b):
    """计算两个向量的余弦相似度 [-1, 1]，越大越相似"""
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def get_embedding_openai(text: str, model: str = "text-embedding-3-small"):
    """调用OpenAI Embedding API"""
    from openai import OpenAI
    client = OpenAI(api_key=API_KEY)
    response = client.embeddings.create(model=model, input=text)
    return response.data[0].embedding


# ============================================================
# 方式B：本地模型（无需API key，但需要安装 sentence-transformers）
# pip install sentence-transformers
# ============================================================

def get_embedding_local(text: str):
    """使用本地sentence-transformers模型"""
    from sentence_transformers import SentenceTransformer
    # 首次运行会下载模型（~130MB），之后缓存
    model = SentenceTransformer("all-MiniLM-L6-v2")
    return model.encode(text).tolist()


# ============================================================
# 主程序
# ============================================================

def main():
    use_openai = bool(API_KEY)
    
    if use_openai:
        print("使用 OpenAI Embedding API")
        embed_func = get_embedding_openai
    else:
        print("未检测到 OPENAI_API_KEY，切换到本地模型")
        print("首次运行需安装: pip install sentence-transformers")
        embed_func = get_embedding_local

    print("\n" + "=" * 60)
    print("练习1：语义相似度")
    print("=" * 60)

    # 测试句子对
    pairs = [
        ("今天天气真好", "今天天气不错", "近义句"),
        ("今天天气真好", "我很喜欢吃披萨", "无关句"),
        ("Python是一门编程语言", "Python是一种编程工具", "近义句"),
        ("Python是一门编程语言", "大象是陆地上最大的动物", "无关句"),
        ("苹果最新手机发布", "iPhone 16正式发售", "近义句（跨表述）"),
        ("股票MACD金叉是买入信号", "DIF上穿DEA意味着看涨", "近义句（专业概念）"),
    ]

    for text1, text2, label in pairs:
        try:
            v1 = embed_func(text1)
            v2 = embed_func(text2)
            sim = cosine_similarity(v1, v2)
            print(f"\n[{label}] 相似度: {sim:.4f}")
            print(f"  A: {text1}")
            print(f"  B: {text2}")
            print(f"  向量维度: {len(v1)}")
        except Exception as e:
            print(f"\n[{label}] 出错: {e}")
            break

    print("\n" + "=" * 60)
    print("练习2：Embedding的算术性质")
    print("=" * 60)

    # 经典例子: 国王 - 男人 + 女人 ≈ 女王
    # 用中文来测试
    word_pairs = [
        ("国王", "男人", "女人", "女王"),
        ("北京", "中国", "日本", "东京"),
        ("跑", "跑步", "走路", "走"),
    ]

    try:
        for w1, w2, w3, expected in word_pairs:
            v1 = np.array(embed_func(w1))
            v2 = np.array(embed_func(w2))
            v3 = np.array(embed_func(w3))
            result_vec = v1 - v2 + v3
            
            # 找最接近的词（在候选词中）
            candidates = [expected, w1, w2, w3, "苹果", "电脑", "汽车"]
            best_word = None
            best_sim = -2
            for cand in candidates:
                cand_vec = np.array(embed_func(cand))
                sim = cosine_similarity(result_vec, cand_vec)
                if sim > best_sim:
                    best_sim = sim
                    best_word = cand
            
            print(f"\n  {w1} - {w2} + {w3} = ?")
            print(f"  期望: {expected}  最接近: {best_word} (相似度: {best_sim:.4f})")
            print(f"  {'✓ 正确!' if best_word == expected else '✗ 不匹配（语义近似但非精确）'}")

    except Exception as e:
        print(f"出错: {e}")

    print("\n" + "=" * 60)
    print("核心理解")
    print("=" * 60)
    print("""
Embedding的本质：
1. 把文字变成固定长度的数字向量（如1536维）
2. 语义相近的文字 → 向量距离近（余弦相似度高）
3. 向量的方向 = 语义方向
4. 这就是为什么LLM能"理解"文字——它把文字映射到了有意义的数学空间

RAG系统靠的就是这个：用户问题 → embedding → 找最近的文档片段 → 喂给LLM
    """)


if __name__ == "__main__":
    main()
