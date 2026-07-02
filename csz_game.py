'''
描述：程序随机生成一个1-100之间的整数，用户通过输入猜测数字，程序提示“猜大了”或“猜小了”，直到猜中为止。可增加计分或限制猜测次数功能。
涉及语法：

random 模块生成随机数
input() 获取用户输入，int() 类型转换
while 循环控制游戏过程
if-elif-else 条件判断
异常处理（处理非数字输入）
扩展：加入多轮游戏，记录用户尝试次数并输出历史最佳成绩。
'''
import random
class CszGame:
    def __init__(self,username='zhangsan'):
        random.seed(20)
        print(f'猜数字游戏初始化,当前参加用户:{username}')
        self.username = username

    def start_game(self):
        number = random.randint(1,100)
        while True:
            input_number = input("请输入数字:")
            try:
                int_number = int(input_number)
                if int_number > number:
                    print("大了")
                elif int_number < number:
                    print("小了")
                else:
                    print("答对了")
                    break
            except ValueError:
                print('您输入的不是数字类型,请重新输入')





if __name__ == '__main__':
    game = CszGame()
    game.start_game()
