'''
1. 制定模版
2. 向模型请求，处理请求返回的数据格式
3. 数据输出到页面或者文件
'''
from string import Template
from openai import OpenAI

msg_template='''
请你帮我出一些英语试题,试题都是填空题，出题的要求如下:
${content}

回答内容请严格遵守：
- 你每次回答都必须严格按照JSON的格式进行返回数据，你应该返回一个JSON数组
- JSON对象中包含question、answer，point三个属性，其中question表示试题的题干，answer表示试题的答案，多个答案使用','进行分隔，point表示试题所属的知识要点
- 例如你的返回格式如下：
[
 {
  "question":"请写出key的复数形式",
  "answer": "keys",
  "point": "名词的复数形式"
 }
]
- 由于用户是中国人，除非题干明确就是英文的形式，否则尽量使用中文描述，point属性必须使用中文进行描述。
'''

key = 'sk-d4397116cac5481ea242346a4ed68173'




def generate_question_by_ai(content:str):
    template = Template(msg_template)
    request_content = template.substitute(content=content)
    print(request_content)
    client = OpenAI(
        api_key=key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    completion = client.chat.completions.create(
        model="qwen-plus",
        messages=[{'role': 'user', 'content': request_content}]
    )
    print(completion.choices[0].message.content)


if __name__ == '__main__':
    content = input("请输入试题内容:")
    if content.strip() != "":
        generate_question_by_ai(content)





























