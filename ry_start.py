import subprocess
import os
import base64
from jproperties import Properties


class RyStarter:
    def __init__(self):
        self.current_dir = os.getcwd()
        self.sql_file='t1.sql'
        self.nacos_home=os.path.join(self.current_dir,'nacos')
        self.nacos_conf='application.properties'
        self.db_type = 'mysql'
        self.base64_key = base64.b64encode(os.urandom(32)).decode()
        self.auth_value = 'nacos-local'
        self.auth_key = 'nacos-local'
        self.db_host = '127.0.0.1'
        self.db_port = '3306'
        self.db_user = 'root'
        self.db_pwd = 'Luoyu666'
        print(f'当前工作工作目录为{self.current_dir}')

    def start(self):
        print('首次启动若以系统，开始构建nacos环境')
        self.init_parameters()
        # self.init_db()
        self.init_nacos()



    def init_parameters(self):
        auth_key = input('请输入nacoskey值(默认为nacos-local):')
        if auth_key.strip() != "":
            self.auth_key = auth_key
        auth_value = input("请输入nacosvalue值(默认值为nacos-local):")
        if auth_value.strip() != "":
            self.auth_value = auth_value

        db_host = input("请输入数据库主机(默认值为本地):")
        if db_host.strip() != "":
            self.db_host = db_host
        db_port = input("请输入数据库端口号(默认为3306)")
        if db_port.strip() != "":
            self.db_port = db_port

        db_user = input("请输入数据库登录用户(默认为root):")
        if db_user.strip() != "":
            self.db_user = db_user




    def init_db(self):
        file_path = os.path.join(self.current_dir,self.sql_file)
        print(f'导入nacos配置数据{file_path}')
        with open(file_path,'rb') as f:
            result = subprocess.run(
                ['/usr/local/mysql/bin/mysql',
                 '-h',
                 self.db_host,
                 '-P',
                 self.db_port,
                 '-u',
                 self.db_user,
                 f'-p{self.db_pwd}']
                ,
                stdin=f,
                check=True,
                capture_output=True  # 可选：捕获输出
            )
            print(result.stderr)


    # 初始化nacos，配置key值
    def init_nacos(self):
        file_path = os.path.join(self.nacos_home,'conf',self.nacos_conf)
        print(f'nacos配置文件地址：{file_path}')
        props = Properties()
        try:
            with open(file_path, 'rb') as f:
                props.load(f)
        except FileNotFoundError:
            pass  # 文件不存在，直接使用空对象

        # 2. 修改或新增属性
        props['nacos.core.auth.plugin.nacos.token.secret.key'] = self.base64_key  # 修改现有值或新增
        props['nacos.core.auth.server.identity.key'] = self.auth_key
        props['nacos.core.auth.server.identity.value'] = self.auth_value
        props['nacos.core.auth.enabled'] = 'true'

        # 3. 删除属性（如果需要）
        #  del props['deprecated.key']

        # 4. 保存回文件（保留注释、顺序、转义字符）
        with open(file_path, 'wb') as f:
            props.store(f, encoding='utf-8')











    def __str__(self):
        return (f'db_type={self.db_type}\n,'
                f'auth_key={self.auth_key}\n,'
                f'auth_value={self.auth_value}\n'
                f'base64_key={self.base64_key}\n'
                f'db_host={self.db_host},db_port={self.db_port},db_user={self.db_user},db_pwd={self.db_pwd}')



ry = RyStarter()
ry.start()
print(ry)







# 1. 执行简单命令
# result = subprocess.run(["ls", "-l"])
# print(f"返回码: {result.returncode}")

# 2. 捕获输出
# result = subprocess.run(["echo", "Hello, World!"], capture_output=True, text=True)
# print(f"输出: {result.stdout}")
# print(f"错误: {result.stderr}")
#
# # 3. 带超时控制
# try:
#     result = subprocess.run(["sleep", "5"], timeout=3)
# except subprocess.TimeoutExpired:
#     print("命令执行超时！")

# 4. 检查命令是否存在
# try:
#     subprocess.run(["java","--version"], check=True)
# except FileNotFoundError:
#     print("命令不存在！")
# except subprocess.CalledProcessError:
#     print("命令执行失败！")
# result = subprocess.run(
#         ['/usr/local/mysql/bin/mysql', '-u', 'root', '--password=Luoyu666', '-e',  'SHOW DATABASES;']
#     ,
#     check=True
#     )
