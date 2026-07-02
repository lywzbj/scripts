import easyocr

print(easyocr.__version__)

reader = easyocr.Reader(['ch_sim','en'],
                        gpu=False,
                        model_storage_directory='./models',
                        download_enabled=False)

result = reader.readtext('t1.png')


for (bbox, text, prob) in result:
    print(f'识别文本：{text}，置信度：{prob:.2f}')