from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit
from datetime import datetime, timedelta
import time
import os
from threading import Lock

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # 设置一个安全的密钥,不用管
socketio = SocketIO(app)  # 初始化 SocketIO

# 读取用户数据
def load_users():
    users = []
    with open('users.txt', 'r', encoding='utf-8') as file:
        for line in file:
            parts = line.strip().split()
            if len(parts) >= 4:
                users.append({
                    'id': parts[0],
                    'name': parts[1],
                    'order': int(parts[2]),
                    'password': parts[3],
                    'status': '未开始'  # 初始状态
                })
    return sorted(users, key=lambda x: x['order'])

# 初始化座位状态
seats = {
    'A1': None, 'A2': None, 'A3': None, 'A4': None, 'A5': None, 
    'B1': None, 'B2': None, 'B3': None, 'B4': None, 'B5': None, 
    'C1': None, 'C2': None, 'C3': None, 'C4': None, 'C5': None, 
    'D1': None, 'D2': None, 'D3': None, 'D4': None, 'D5': None, 
    'E1': None, 'E2': None, 'E3': None, 'E4': None, 'E5': None, 
    'F1': None, 'F2': None, 'F3': None, 'F4': None, 'F5': None, 
    'G1': None, 'G2': None
}

# 日志文件
log_file = 'selection_log.txt'

# 管理员账号
admin_username = 'admin'
admin_password = 'admin12345'

# 选座开始时间
start_time = None

# 当前选座用户的顺序号
current_order = 1

# 当前选座用户的开始时间
current_user_start_time = None

# 线程锁
thread_lock = Lock()

# 后台计时线程
def background_thread():
    global current_order, current_user_start_time
    while True:
        with thread_lock:
            if start_time and datetime.now() >= start_time:
                users = load_users()
                if current_order <= len(users):
                    current_user = users[current_order - 1]
                    if current_user_start_time is None:
                        current_user_start_time = datetime.now()
                        current_user['status'] = '进行中'
                    else:
                        elapsed_time = datetime.now() - current_user_start_time
                        if elapsed_time > timedelta(minutes=1):
                            # 记录日志：用户超时未选座
                            with open(log_file, 'a', encoding='utf-8') as f:
                                f.write(f"{datetime.now()} - {current_user['name']} 未在1分钟内选择，视为弃权\n")
                            current_user['status'] = '弃权'
                            current_order += 1
                            current_user_start_time = datetime.now()
                            socketio.emit('update', {
                                'current_user': users[current_order - 1]['name'] if current_order <= len(users) else None,
                                'seats': seats,
                                'users': users,
                                'remaining_time': 60
                            })
                        else:
                            remaining_time = 60 - elapsed_time.seconds
                            socketio.emit('update', {
                                'current_user': current_user['name'],
                                'seats': seats,
                                'users': users,
                                'remaining_time': remaining_time
                            })
                else:
                    socketio.emit('update', {
                        'current_user': None,
                        'seats': seats,
                        'users': users,
                        'remaining_time': 0
                    })
        socketio.sleep(1)

@app.route('/')
def index():
    global start_time, current_order
    users = load_users()
    current_user = next((user for user in users if user['order'] == current_order), None)
    return render_template('index.html', users=users, current_user=current_user, seats=seats, start_time=start_time)

@app.route('/select_seat', methods=['POST'])
def select_seat():
    global start_time, current_order, current_user_start_time
    if start_time is None or datetime.now() < start_time:
        return jsonify({'error': '选座尚未开始'})

    name = request.form.get('name')
    student_id = request.form.get('student_id')
    password = request.form.get('password')
    seat = request.form.get('seat')

    users = load_users()
    user = next((user for user in users if user['name'] == name and user['id'] == student_id and user['password'] == password), None)
    if not user:
        return jsonify({'error': '用户信息错误'})

    # 检查用户是否已经完成选座
    if user['status'] == '已完成':
        return jsonify({'error': '您已经完成选座，不可再次选择'})

    # 检查当前选座人是否与用户姓名匹配
    current_user = next((user for user in users if user['order'] == current_order), None)
    if not current_user or current_user['name'] != name:
        return jsonify({'error': '当前不是您的选座时间'})

    if seat not in seats or seats[seat] is not None:
        return jsonify({'error': '座位不可选'})

    seats[seat] = name
    user['status'] = '已完成'
    current_order += 1
    current_user_start_time = datetime.now()

    # 记录日志：用户选座
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now()} - {name} 选择了 {seat}\n")

    # 广播更新信息
    socketio.emit('update', {
        'current_user': users[current_order - 1]['name'] if current_order <= len(users) else None,
        'seats': seats,
        'users': users,
        'remaining_time': 60
    })

    return jsonify({'success': True})

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == admin_username and password == admin_password:
            session['admin'] = True
            return redirect(url_for('set_start_time'))  # 登录成功后跳转到设置开始时间页面
        else:
            return render_template('admin_login.html', error='账号或密码错误')
    return render_template('admin_login.html')

@app.route('/set_start_time', methods=['GET', 'POST'])
def set_start_time():
    if 'admin' not in session:
        return redirect(url_for('admin'))

    global start_time
    if request.method == 'POST':
        start_time_str = request.form.get('start_time')
        try:
            start_time = datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S')
            return jsonify({'success': True})
        except ValueError:
            return jsonify({'error': '时间格式错误，请使用 YYYY-MM-DD HH:MM:SS 格式'})
    return render_template('set_start_time.html')

# WebSocket 事件：客户端连接
@socketio.on('connect')
def handle_connect():
    users = load_users()
    emit('update', {
        'current_user': users[current_order - 1]['name'] if current_order <= len(users) else None,
        'seats': seats,
        'users': users,
        'remaining_time': 60
    })

# 启动后台线程
@socketio.on('start_timer')
def start_timer():
    socketio.start_background_task(background_thread)

if __name__ == '__main__':
    socketio.run(app, port=5000, debug=True)
