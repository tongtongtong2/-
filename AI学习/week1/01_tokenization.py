"""
第1周 Day1-2 练习：Tokenization
理解Token是什么，中英文tokenization的差异。

运行: python 01_tokenization.py
"""

import tiktoken

print("=" * 60)
print("练习1：Tokenization基础")
print("=" * 60)

# GPT-4使用的tokenizer
enc = tiktoken.encoding_for_model("gpt-4")

def show_tokens(text: str, label: str = ""):
    """展示文本的token数量和切分结果"""
    tokens = enc.encode(text)
    print(f"\n--- {label} ---")
    print(f"原文: {text}")
    print(f"Token数: {len(tokens)}")
    print(f"Token IDs: {tokens[:20]}{'...' if len(tokens) > 20 else ''}")
    print(f"解码验证: {enc.decode(tokens[:10])}..." if len(tokens) > 10 else enc.decode(tokens))
    # 逐token显示
    print(f"逐token: ", end="")
    for t in enc.decode_tokens_bytes(tokens[:15]):
        try:
            print(f"[{t.decode('utf-8', errors='replace')}]", end=" ")
        except:
            print(f"[?]", end=" ")
    print()

# ===== 中文 vs 英文 =====
show_tokens("人工智能正在改变世界", "中文")
show_tokens("Artificial intelligence is changing the world", "英文（同样意思）")
show_tokens("AI正在改变世界", "中英混合")

# ===== 不同类型文本 =====
show_tokens("Hello, world!", "简单英文")
show_tokens("中华人民共和国", "中文词语")
show_tokens("def hello(): print('world')", "代码")

# ===== 思考题 =====
print("\n" + "=" * 60)
print("思考题")
print("=" * 60)
questions = [
    ("苹果很好吃", "苹果手机很好用"),
    ("我今天很开心", "I am very happy today"),
    ("OpenAI发布了GPT-5", "OpenAI released GPT-5"),
]
for cn, en in questions:
    cn_tokens = len(enc.encode(cn))
    en_tokens = len(enc.encode(en))
    print(f"\n中文({cn_tokens}tokens): {cn}")
    print(f"英文({en_tokens}tokens): {en}")
    print(f"中文是英文的 {cn_tokens/en_tokens:.1f}x 倍")

print("\n结论：中文通常比英文消耗更多token（1.5-3倍），因为中文字符多且tokenizer训练时英文占优")
