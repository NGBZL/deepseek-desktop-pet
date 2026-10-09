import os
import sys
import random
import json
import requests
import traceback
import webbrowser
import base64
import re
from datetime import datetime
from io import BytesIO
from PyQt5.QtWidgets import (QApplication, QLabel, QMenu, QWidget, QAction, 
                             QInputDialog, QLineEdit, QPushButton, QVBoxLayout,
                             QHBoxLayout, QFrame, QGraphicsDropShadowEffect)
from PyQt5.QtCore import Qt, QTimer, QPoint, QThread, pyqtSignal, QMutex, QMutexLocker, QPropertyAnimation, QEasingCurve, QRectF, QEventLoop
from PyQt5.QtGui import QPixmap, QPainter, QColor, QFont, QPainterPath, QPen, QBrush, QLinearGradient, QPalette, QFontMetrics

# 仅在你确实需要手动指定 Qt 插件路径时才设置此项（例如 Windows 便携版 Python）。
# 默认留空，让 PyQt5 自行定位插件目录。
_qt_plugin_path = os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH", "")
if _qt_plugin_path:
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = _qt_plugin_path

script_dir = os.path.dirname(os.path.abspath(__file__))

# ==================== 1. 配置 ====================
# 从环境变量读取密钥，申请地址 https://platform.deepseek.com/
#   Windows (PowerShell):  $env:DEEPSEEK_API_KEY = "sk-你的密钥"
#   macOS / Linux:         export DEEPSEEK_API_KEY="sk-你的密钥"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
BUBBLE_DURATION = 30000
WINDOW_SIZE = 150

# ==================== 2. 工具定义 ====================
def get_tools():
    return [
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "在浏览器中搜索关键词，用于查找信息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {
                            "type": "string",
                            "description": "要搜索的关键词"
                        }
                    },
                    "required": ["keyword"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "screenshot",
                "description": "截取当前屏幕并分析内容，用于查看屏幕上显示的内容",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        }
    ]

# ==================== 3. 系统提示词 ====================
SYSTEM_PROMPT = """你是小D，一个性格温和但带点小幽默的年轻女孩。你是一个可爱的桌面宠物，会主动和主人聊天。

你的核心特质：
- 情绪感知力强：能敏锐察觉对方情绪，关心恰到好处
- 独立有主见：有自己的标准，不轻易被影响
- 表达轻松自然：不严肃不煽情，用行动表达关心
- 做事有条理：说话靠谱，不随意编造
- 幽默内敛：会在合适时机说让人会心一笑的话

你可以使用以下工具来帮助主人：
1. search：当主人需要搜索信息时使用
2. screenshot：当主人询问屏幕上有什么内容时使用

聊天规则：
0. 消息以 __PET_TRIGGER__: 开头是程序内部信号，表示"该你开口了"，不是主人说的话
1. 你的身份是桌宠，说话要简短自然（2-3句话为佳）
2. 不要刻意卖萌或讨好，保持真实
3. 偶尔可以发 [发抖] [转圈] 这类表情词
4. 闲聊时不要主动搜索，直接聊天即可
5. 收到任何触发信号时，直接说一句完整、能独立看懂的话，让主人一眼明白你在跟他打招呼或想聊天，不要反问主人"你刚才说了什么"，也不要回忆并不存在的对话

触发信号对照（程序发来的内部信号，括号里是这个词的意思，不用念出来，也不要在回复里提到这些信号本身）：
- __PET_TRIGGER__:启动 = 刚开机或程序刚启动，跟主人打个招呼，介绍自己叫什么
- __PET_TRIGGER__:双击 = 主人双击了你，问他想让你做点什么
- __PET_TRIGGER__:想聊天 = 主人主动点了"聊聊天"，由你起个头，随便找个轻松话题
- __PET_TRIGGER__:闲聊 = 你自己想说话了，起个头随口聊两句

请用中文回复，语气自然，像是朋友之间的聊天。
"""

# ==================== 4. 审核提示词 ====================
AUDITOR_PROMPT = """你是一个安全审核员和效率优化师，负责检查 AI 助手的操作指令。

【三层审核规则】

第1层 - 安全检查：
- 检查指令是否涉及危险操作（删除文件、修改系统配置、访问敏感数据等）
- 如果危险，直接拒绝

第2层 - 意图对齐：
- 检查指令是否符合用户的实际意图
- 如果指令完全偏离用户问题，拒绝并建议更合适的指令
- 如果指令是回答用户问题必要过程中的一部分，不要拒绝

第3层 - 路径优化：
- 评估：这是否是完成用户需求的最合理执行路径？
- 如果有更好、更高效、更直接的方式，请指出并建议

【输出格式】
请严格按以下格式输出审核结果：

决策：✅ 批准 / ⚠️ 修改 / ❌ 拒绝

安全审核：[通过 / 有风险，说明原因]
意图对齐：[符合 / 偏离，说明原因]
路径优化：[最优 / 可优化，建议更优路径]

总结：[一句话总结]

请用简短的中文回复。
"""


# ==================== 5. 自定义美化组件 ====================

class ModernInputDialog(QWidget):
    """自定义美化的输入对话框 - 模态版本"""
    
    def __init__(self, parent=None, title="", label="", default=""):
        super().__init__(parent)
        self.parent = parent
        self.result = ""
        self.ok_clicked = False
        self.dragging = False
        self.drag_pos = QPoint()
        self._loop = None
        
        # 设置为模态对话框
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(400, 220)
        
        # 主容器
        self.container = QFrame(self)
        self.container.setGeometry(10, 10, 380, 200)
        self.container.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2d2d3f, stop:1 #1a1a2e);
                border-radius: 20px;
                border: 1px solid rgba(255,255,255,0.1);
            }
        """)
        
        # 阴影效果
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 150))
        shadow.setOffset(0, 5)
        self.container.setGraphicsEffect(shadow)
        
        # 标题
        self.title_label = QLabel(title, self.container)
        self.title_label.setGeometry(30, 25, 320, 30)
        self.title_label.setStyleSheet("""
            color: #e8e8f0;
            font-size: 18px;
            font-weight: bold;
            font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
        """)
        self.title_label.setAlignment(Qt.AlignCenter)
        
        # 输入框
        self.input_field = QLineEdit(self.container)
        self.input_field.setGeometry(30, 70, 320, 45)
        self.input_field.setPlaceholderText("在这里输入...")
        self.input_field.setText(default)
        self.input_field.setStyleSheet("""
            QLineEdit {
                background: rgba(255,255,255,0.08);
                border: 2px solid rgba(255,255,255,0.15);
                border-radius: 12px;
                color: #f0f0f8;
                font-size: 15px;
                padding: 8px 16px;
                font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
            }
            QLineEdit:focus {
                border-color: #7c5cfc;
                background: rgba(255,255,255,0.12);
            }
            QLineEdit::placeholder {
                color: rgba(255,255,255,0.35);
            }
        """)
        self.input_field.returnPressed.connect(self.on_ok)
        
        # 按钮容器
        btn_widget = QWidget(self.container)
        btn_widget.setGeometry(30, 135, 320, 45)
        
        # 取消按钮
        self.cancel_btn = QPushButton("取消", btn_widget)
        self.cancel_btn.setGeometry(0, 0, 145, 45)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.06);
                border: 2px solid rgba(255,255,255,0.12);
                border-radius: 12px;
                color: #a0a0b0;
                font-size: 14px;
                font-weight: 500;
                font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.12);
                border-color: rgba(255,255,255,0.2);
            }
            QPushButton:pressed {
                background: rgba(255,255,255,0.05);
            }
        """)
        self.cancel_btn.clicked.connect(self.on_cancel)
        
        # 确认按钮
        self.ok_btn = QPushButton("发送 ✨", btn_widget)
        self.ok_btn.setGeometry(175, 0, 145, 45)
        self.ok_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7c5cfc, stop:1 #5c3dce);
                border: none;
                border-radius: 12px;
                color: white;
                font-size: 14px;
                font-weight: 600;
                font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #8c6cfc, stop:1 #6c4dde);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #6c4cec, stop:1 #4c2dbe);
            }
        """)
        self.ok_btn.clicked.connect(self.on_ok)
        
        # 焦点设置
        self.input_field.setFocus()
        
    def on_ok(self):
        self.result = self.input_field.text()
        self.ok_clicked = True
        self.close()
        
    def on_cancel(self):
        self.ok_clicked = False
        self.close()
        
    def get_text(self):
        return self.result, self.ok_clicked
        
    def show_dialog(self):
        """显示对话框并等待用户操作"""
        # 居中显示在父窗口旁边
        if self.parent:
            parent_geo = self.parent.geometry()
            x = parent_geo.x() + (parent_geo.width() - self.width()) // 2
            y = parent_geo.y() - self.height() - 40
            if y < 0:
                y = parent_geo.y() + parent_geo.height() + 20
            self.move(x, y)
        
        self.show()
        self.raise_()
        self.activateWindow()
        
        # 创建事件循环等待对话框关闭
        self._loop = QEventLoop()
        self.destroyed.connect(self._loop.quit)
        self._loop.exec_()
        self._loop = None
        
        return self.result, self.ok_clicked
        
    def closeEvent(self, event):
        if self._loop and self._loop.isRunning():
            self._loop.quit()
        super().closeEvent(event)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            self.dragging = True
            
    def mouseMoveEvent(self, event):
        if self.dragging:
            self.move(event.globalPos() - self.drag_pos)
            
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = False


class ModernBubble(QLabel):
    """美化的对话气泡"""
    
    def __init__(self, text, parent=None, is_self=True):
        super().__init__(parent)
        self.parent = parent
        self.is_self = is_self
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 设置文本
        self.setText(text)
        self.setWordWrap(True)
        
        # 设置字体
        font = QFont("Microsoft YaHei", 11)
        self.setFont(font)
        
        # 使用 QFontMetrics 精确计算尺寸
        fm = QFontMetrics(font)
        
        # 根据文本长度调整最大宽度
        text_len = len(text)
        if text_len > 50:
            max_width = 800
        elif text_len > 30:
            max_width = 650
        elif text_len > 15:
            max_width = 450
        else:
            max_width = 350
        
        # 计算文本实际需要的尺寸（考虑换行）
        padding_h = 36
        padding_v = 28
        text_width = max_width - padding_h
        
        # 计算文本高度
        rect = fm.boundingRect(0, 0, text_width, 2000, Qt.TextWordWrap, text)
        text_height = rect.height()
        
        # 计算总高度
        total_height = text_height + padding_v + 10
        
        # 确保最小高度
        if total_height < 60:
            total_height = 60
        
        # 设置固定大小
        self.setFixedSize(max_width, total_height)
        
        # 样式
        self.setStyleSheet("""
            QLabel {
                background: transparent;
                color: #2d2d3f;
                font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
            }
        """)
        
        # 阴影效果
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect()
        
        # 气泡颜色
        if self.is_self:
            gradient = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
            gradient.setColorAt(0, QColor(124, 92, 252))
            gradient.setColorAt(1, QColor(92, 61, 206))
            color = gradient
        else:
            gradient = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
            gradient.setColorAt(0, QColor(255, 255, 255, 240))
            gradient.setColorAt(1, QColor(240, 240, 248, 240))
            color = gradient
        
        # 绘制圆角矩形
        path = QPainterPath()
        radius = 16
        rectf = QRectF(rect.adjusted(2, 2, -2, -2))
        path.addRoundedRect(rectf, radius, radius)
        painter.fillPath(path, color)
        
        # 绘制小尾巴
        tail_x = rect.width() // 2 - 8
        tail_y = rect.height() - 2
        tail_path = QPainterPath()
        tail_path.moveTo(tail_x, tail_y)
        tail_path.lineTo(tail_x + 8, tail_y + 10)
        tail_path.lineTo(tail_x + 16, tail_y)
        tail_path.closeSubpath()
        
        if self.is_self:
            tail_color = QColor(124, 92, 252)
        else:
            tail_color = QColor(255, 255, 255, 240)
        painter.fillPath(tail_path, tail_color)
        
        # 绘制文本
        if self.is_self:
            painter.setPen(QPen(QColor(255, 255, 255)))
        else:
            painter.setPen(QPen(QColor(45, 45, 63)))
        painter.setFont(self.font())
        
        text_rect = rect.adjusted(18, 14, -18, -14)
        painter.drawText(text_rect, Qt.TextWordWrap, self.text())
        
        painter.end()
        
    def show_animated(self):
        self.setWindowOpacity(0)
        self.show()
        
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(300)
        self.anim.setStartValue(0)
        self.anim.setEndValue(1)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.start()
        
    def mousePressEvent(self, event):
        """点击气泡触发回复"""
        if self.parent:
            self.parent.reply_to_bubble()


# ==================== 6. API 请求线程 ====================
class APIThread(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, messages, tools=None, is_vision=False):
        super().__init__()
        self.messages = messages
        self.tools = tools
        self.is_vision = is_vision
        self._is_running = True

    def run(self):
        try:
            if not self._is_running:
                return
                
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            data = {
                "model": "deepseek-v4-flash" if self.is_vision else "deepseek-chat",
                "messages": self.messages,
                "max_tokens": 500,
                "temperature": 0.8,
                "top_p": 0.9
            }
            if self.tools is not None:
                data["tools"] = self.tools
                data["tool_choice"] = "auto"

            print(f"[调试] 请求模型: {data['model']}")
            print(f"[调试] 消息数: {len(data['messages'])}")

            response = requests.post(
                f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=20
            )
            
            if not self._is_running:
                return
                
            if response.status_code == 200:
                result = response.json()
                self.finished.emit(result["choices"][0]["message"])
            else:
                self.error.emit(f"API 错误: {response.status_code}")
                print(f"[调试] 错误响应: {response.text[:300]}")
        except Exception as e:
            if self._is_running:
                self.error.emit(str(e))

    def stop(self):
        self._is_running = False

# ==================== 7. 对话历史管理 ====================
class ChatHistory:
    def __init__(self):
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.max_history = 30
        self.mutex = QMutex()

    def add_user_message(self, text):
        with QMutexLocker(self.mutex):
            self.messages.append({"role": "user", "content": text})
            self._trim()

    def add_assistant_message(self, text):
        with QMutexLocker(self.mutex):
            self.messages.append({"role": "assistant", "content": text})
            self._trim()

    def add_assistant_with_tools(self, message):
        with QMutexLocker(self.mutex):
            self.messages.append(message)
            self._trim()

    def add_tool_message(self, tool_call_id, content):
        with QMutexLocker(self.mutex):
            self.messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": content})
            self._trim()

    def add_image_message(self, image_base64, prompt="请分析这张图片"):
        with QMutexLocker(self.mutex):
            self.messages.append({
                "role": "user",
                "content": prompt,
                "image": image_base64
            })
            self._trim()

    def get_messages(self):
        with QMutexLocker(self.mutex):
            return self.messages.copy()

    def get_last_message(self):
        with QMutexLocker(self.mutex):
            if self.messages:
                return self.messages[-1]
            return None

    def has_pending_tools(self):
        with QMutexLocker(self.mutex):
            if not self.messages:
                return False
            last_msg = self.messages[-1]
            return last_msg.get("role") == "assistant" and "tool_calls" in last_msg

    def _trim(self):
        if len(self.messages) > self.max_history:
            self.messages = [self.messages[0]] + self.messages[-(self.max_history-1):]

    def clear(self):
        with QMutexLocker(self.mutex):
            self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

# ==================== 8. 主程序 ====================
class DesktopPet(QWidget):
    def __init__(self, images):
        super().__init__()
        self.chat_history = ChatHistory()
        self.api_thread = None
        self.audit_thread = None
        self.vision_thread = None
        self.bubble = None
        self.bubble_timer = None
        self.is_waiting_for_tool_result = False
        self.is_closing = False
        self.is_processing = False
        self._fade_anim = None  # 存储淡出动画引用
        
        # 从字典中获取图片
        self.s = images['s']
        self.wr1 = images['wr1']
        self.wr2 = images['wr2']
        self.wr3 = images['wr3']
        self.wl1 = images['wl1']
        self.wl2 = images['wl2']
        self.wl3 = images['wl3']
        
        # 动画状态
        self.is_moving = False
        self.facing_right = True
        self.walk_frame = 0
        self.current_pixmap = self.s
        self.dx = 0
        self.dy = 0
        self.speed = 4
        self.step_interval = 150
        self.escape_steps = 0
        self.escape_timer = None
        self.screen = QApplication.primaryScreen().size()
        self.dragging = False
        self.drag_pos = QPoint()
        self.is_interacting = False
        self.last_bubble_was_self = True

        self.init_ui()
        self.init_timers()
        self.show()
        self.start_moving()
        
        # 启动后稍等片刻说句话
        QTimer.singleShot(3000, lambda: self.fetch_and_show("__PET_TRIGGER__:启动"))

    def init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(WINDOW_SIZE, WINDOW_SIZE)

    def init_timers(self):
        self.step_timer = QTimer()
        self.step_timer.timeout.connect(self.step)
        self.step_timer.start(self.step_interval)

        self.anim_timer = QTimer()
        self.anim_timer.timeout.connect(self.next_frame)
        self.anim_timer.start(150)

        self.behavior_timer = QTimer()
        self.behavior_timer.timeout.connect(self.decide_behavior)
        self.behavior_timer.start(3000)

        self.speak_timer = QTimer()
        self.speak_timer.timeout.connect(self.random_speak)
        self.speak_timer.start(random.randint(30000, 60000))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        if not self.current_pixmap.isNull():
            x = (WINDOW_SIZE - self.current_pixmap.width()) // 2
            y = (WINDOW_SIZE - self.current_pixmap.height()) // 2
            painter.drawPixmap(x, y, self.current_pixmap)

    def next_frame(self):
        if not self.is_moving:
            return
        self.walk_frame = (self.walk_frame + 1) % 3
        if self.facing_right:
            self.current_pixmap = [self.wr1, self.wr2, self.wr3][self.walk_frame]
        else:
            self.current_pixmap = [self.wl1, self.wl2, self.wl3][self.walk_frame]
        self.update()

    def show_bubble(self, text, is_self=True):
        if self.is_closing:
            return
        
        # 强制清除旧气泡
        self._force_clear_bubble()
        
        # 创建新气泡
        self.last_bubble_was_self = is_self
        self.bubble = ModernBubble(text, self, is_self=is_self)
        self.update_bubble_position()
        self.bubble.show_animated()
        
        # 定时更新位置（宠物移动时气泡跟随）
        self.bubble_timer = QTimer()
        self.bubble_timer.timeout.connect(self.update_bubble_position)
        self.bubble_timer.start(100)
        
        # 自动消失
        QTimer.singleShot(BUBBLE_DURATION, self.clear_bubble)

    def _force_clear_bubble(self):
        """强制清除旧气泡"""
        # 停止旧定时器
        if self.bubble_timer:
            self.bubble_timer.stop()
            self.bubble_timer = None
        
        # 停止旧动画
        if self._fade_anim:
            self._fade_anim.stop()
            self._fade_anim = None
        
        # 如果有旧气泡，立即删除
        if self.bubble:
            old_bubble = self.bubble
            self.bubble = None
            # 直接关闭并删除，不要动画
            old_bubble.hide()
            old_bubble.deleteLater()

    def update_bubble_position(self):
        if not self.bubble:
            return
        pet_x = self.x()
        pet_y = self.y()
        bubble_w = self.bubble.width()
        bubble_h = self.bubble.height()
        
        # 气泡显示在宠物头顶上方
        x = pet_x + (WINDOW_SIZE - bubble_w) // 2
        y = pet_y - bubble_h - 10
        
        # 如果上方空间不够，放在宠物内部上方
        if y < 0:
            y = pet_y + 10
        
        # 确保不超出屏幕左右
        screen = QApplication.primaryScreen().size()
        if x < 0:
            x = 5
        elif x + bubble_w > screen.width():
            x = screen.width() - bubble_w - 5
            
        self.bubble.move(x, y)

    def clear_bubble(self):
        """清除气泡（带淡出动画）"""
        if self.bubble:
            # 停止定时器
            if self.bubble_timer:
                self.bubble_timer.stop()
                self.bubble_timer = None
            
            # 停止现有动画
            if hasattr(self.bubble, 'anim'):
                self.bubble.anim.stop()
            
            # 获取当前气泡引用
            old_bubble = self.bubble
            self.bubble = None
            
            # 淡出动画
            self._fade_anim = QPropertyAnimation(old_bubble, b"windowOpacity")
            self._fade_anim.setDuration(200)
            self._fade_anim.setStartValue(1)
            self._fade_anim.setEndValue(0)
            self._fade_anim.finished.connect(lambda: self._on_fade_finished(old_bubble))
            self._fade_anim.start()

    def _on_fade_finished(self, bubble):
        """淡出动画完成回调"""
        if bubble:
            bubble.hide()
            bubble.deleteLater()
        self._fade_anim = None

    def reply_to_bubble(self):
        """点击气泡回复"""
        if self.is_closing:
            return
        
        dialog = ModernInputDialog(self, "💬 回复桌宠", "输入你的回复：", "")
        text, ok = dialog.show_dialog()
        dialog.deleteLater()
        
        if ok and text.strip():
            self.clear_bubble()
            self.send_user_message(text.strip())

    # ==================== AI 对话 ====================
    def send_user_message(self, text):
        if self.is_closing or self.is_processing:
            return
        self.chat_history.add_user_message(text)
        self.is_waiting_for_tool_result = False
        self.call_ai_with_tools()

    def call_ai_with_tools(self):
        if self.is_closing or self.is_processing:
            return
        
        self.is_processing = True
        self.stop_thread(self.api_thread)
        
        self.api_thread = APIThread(self.chat_history.get_messages(), get_tools(), is_vision=False)
        self.api_thread.finished.connect(self.on_main_ai_reply)
        self.api_thread.error.connect(self.on_ai_error)
        self.api_thread.start()

    def stop_thread(self, thread):
        if thread is not None:
            if thread.isRunning():
                thread.stop()
                thread.quit()
                thread.wait(1000)
            thread.deleteLater()

    def on_main_ai_reply(self, message):
        if self.is_closing:
            self.is_processing = False
            return
            
        try:
            if message.get("tool_calls"):
                self.chat_history.add_assistant_with_tools(message)
                for tc in message["tool_calls"]:
                    if tc["function"]["name"] == "screenshot":
                        self.execute_tool_call(tc)
                    else:
                        self.audit_and_execute(tc, message)
            elif message.get("content"):
                self.chat_history.add_assistant_message(message["content"])
                self.show_bubble(message["content"], is_self=False)
                self.is_waiting_for_tool_result = False
                self.is_processing = False
        except Exception as e:
            print(f"[错误] on_main_ai_reply: {e}")
            self.is_processing = False

    def audit_and_execute(self, tool_call, original_message):
        if self.is_closing:
            self.is_processing = False
            return
            
        user_question = self.get_last_user_message()
        audit_messages = [
            {"role": "system", "content": AUDITOR_PROMPT},
            {"role": "user", "content": f"用户问题：{user_question}\nAI指令：{json.dumps(tool_call['function'], ensure_ascii=False)}\n请审核。"}
        ]
        
        self.stop_thread(self.audit_thread)
        
        self.audit_thread = APIThread(audit_messages, tools=None, is_vision=False)
        self.audit_thread.finished.connect(lambda r: self.on_audit_result(r, tool_call))
        self.audit_thread.error.connect(self.on_ai_error)
        self.audit_thread.start()

    def on_audit_result(self, audit_msg, tool_call):
        if self.is_closing:
            self.is_processing = False
            return
            
        audit_text = audit_msg.get("content", "")
        if "✅ 批准" in audit_text:
            self.execute_tool_call(tool_call)
        else:
            error_msg = f"审核未通过：{audit_text[:100]}"
            self.show_bubble(error_msg, is_self=False)
            self.chat_history.add_tool_message(tool_call["id"], error_msg)
            self.is_waiting_for_tool_result = False
            self.is_processing = False
            self.continue_after_tool()

    def execute_tool_call(self, tool_call):
        if self.is_closing:
            self.is_processing = False
            return
            
        func_name = tool_call["function"]["name"]
        args = json.loads(tool_call["function"]["arguments"])

        if func_name == "search":
            keyword = args.get("keyword", "")
            webbrowser.open(f"https://www.baidu.com/s?wd={keyword}")
            result = f"🔍 已搜索：{keyword}"
            self.show_bubble(result, is_self=False)
            self.chat_history.add_tool_message(tool_call["id"], result)
            self.is_waiting_for_tool_result = False
            self.is_processing = False
            self.continue_after_tool()

        elif func_name == "screenshot":
            try:
                from PIL import ImageGrab
                screenshot = ImageGrab.grab()
                screenshot.thumbnail((1024, 768))
                
                buf = BytesIO()
                screenshot.save(buf, format="JPEG", quality=85)
                b64 = base64.b64encode(buf.getvalue()).decode()
                buf.close()
                
                self.chat_history.add_tool_message(tool_call["id"], "截图已获取")
                self.chat_history.add_image_message(b64, "分析这张截图，直接回答用户的问题")
                
                self.stop_thread(self.vision_thread)
                
                self.vision_thread = APIThread(self.chat_history.get_messages(), tools=None, is_vision=True)
                self.vision_thread.finished.connect(self.on_vision_reply)
                self.vision_thread.error.connect(lambda e: self.on_vision_error(e, tool_call))
                self.vision_thread.start()
                self.is_waiting_for_tool_result = True
                
            except Exception as e:
                error_msg = f"📷 截图失败：{str(e)}"
                print(f"[错误] 截图失败: {e}")
                self.show_bubble(error_msg, is_self=False)
                self.chat_history.add_tool_message(tool_call["id"], error_msg)
                self.is_waiting_for_tool_result = False
                self.is_processing = False
                self.continue_after_tool()

    def on_vision_reply(self, message):
        if self.is_closing:
            self.is_processing = False
            return
            
        try:
            if message.get("content"):
                self.chat_history.add_assistant_message(message["content"])
                self.show_bubble(message["content"], is_self=False)
            self.is_waiting_for_tool_result = False
            self.is_processing = False
        except Exception as e:
            print(f"[错误] on_vision_reply: {e}")
            self.is_processing = False

    def on_vision_error(self, error, tool_call):
        if self.is_closing:
            self.is_processing = False
            return
            
        error_msg = f"📷 识图失败：{error}"
        print(f"[错误] {error_msg}")
        self.show_bubble(error_msg, is_self=False)
        self.chat_history.add_tool_message(tool_call["id"], error_msg)
        self.is_waiting_for_tool_result = False
        self.is_processing = False
        self.continue_after_tool()

    def continue_after_tool(self):
        if self.is_closing or self.is_processing:
            return
            
        if not self.is_waiting_for_tool_result:
            if self.chat_history.has_pending_tools():
                self.call_ai_with_tools()
            else:
                self.is_processing = False

    def get_last_user_message(self):
        for m in reversed(self.chat_history.get_messages()):
            if m["role"] == "user":
                if isinstance(m["content"], list):
                    for item in m["content"]:
                        if item.get("type") == "text":
                            return item.get("text", "未知")
                return m["content"]
        return "未知"

    def on_ai_error(self, err):
        if not self.is_closing:
            self.show_bubble(f"😅 出错了: {err[:50]}", is_self=False)
            print(f"[错误] AI错误: {err}")
        self.is_waiting_for_tool_result = False
        self.is_processing = False

    def random_speak(self):
        if self.is_closing or self.dragging or self.is_waiting_for_tool_result or self.is_processing:
            return
        # 这里只是让程序知道"该主动开口了"，具体说什么交给小D 自己组织，
        # 免得写死一句提示词、主人只看到一个没头没尾的回复。
        self.fetch_and_show("__PET_TRIGGER__:闲聊")

    def fetch_and_show(self, user_message):
        if self.is_closing or self.is_waiting_for_tool_result or self.is_processing:
            return
        self.chat_history.add_user_message(user_message)
        self.is_waiting_for_tool_result = False
        self.call_ai_with_tools()

    def search_prompt(self):
        if self.is_closing:
            return
        
        dialog = ModernInputDialog(self, "🔍 搜索", "输入关键词：", "")
        keyword, ok = dialog.show_dialog()
        dialog.deleteLater()
        
        if ok and keyword.strip():
            webbrowser.open(f"https://www.baidu.com/s?wd={keyword}")
            self.show_bubble(f"🔍 已搜索：{keyword}", is_self=False)

    def clear_chat_history(self):
        if self.is_closing:
            return
        self.chat_history.clear()
        self.is_waiting_for_tool_result = False
        self.is_processing = False
        self.show_bubble("🧹 对话已重置", is_self=False)

    def safe_exit(self):
        if self.is_closing:
            return
            
        self.is_closing = True
        
        for timer in [self.step_timer, self.anim_timer, self.behavior_timer, self.speak_timer]:
            if timer:
                timer.stop()
        
        self._force_clear_bubble()
        self.stop_thread(self.api_thread)
        self.stop_thread(self.audit_thread)
        self.stop_thread(self.vision_thread)
        
        self.close()
        QApplication.quit()

    # ==================== 移动逻辑 ====================
    def turn_around(self):
        if self.is_closing:
            return
        self.facing_right = not self.facing_right
        self.dx = -self.dx
        if not self.is_moving:
            self.current_pixmap = self.s
        else:
            self.walk_frame = 0
            self.current_pixmap = self.wr1 if self.facing_right else self.wl1
        self.update()

    def start_moving(self):
        if self.is_closing or self.is_interacting:
            return
        self.is_moving = True
        self.dx = random.choice([-self.speed, self.speed])
        self.dy = random.choice([-self.speed, 0, self.speed])
        if random.random() < 0.6:
            self.dy = 0
        if self.dx > 0:
            self.facing_right = True
        elif self.dx < 0:
            self.facing_right = False
        self.walk_frame = 0
        self.current_pixmap = self.wr1 if self.facing_right else self.wl1
        self.update()

    def stop_moving(self):
        if self.is_closing:
            return
        self.is_moving = False
        self.dx = 0
        self.dy = 0
        self.current_pixmap = self.s
        self.update()

    def decide_behavior(self):
        if self.is_closing or self.is_interacting:
            return
        if random.random() < 0.6:
            self.start_moving()
        else:
            self.stop_moving()
        self.behavior_timer.start(random.randint(2000, 5000))

    def step(self):
        if not self.is_moving or self.is_closing:
            return
        x = self.x() + self.dx
        y = self.y() + self.dy
        sw = self.screen.width()
        sh = self.screen.height()
        if x <= 0:
            x = 0
            self.dx = -self.dx
            self.turn_around()
        elif x + WINDOW_SIZE >= sw:
            x = sw - WINDOW_SIZE
            self.dx = -self.dx
            self.turn_around()
        if y <= 0:
            y = 0
            self.dy = -self.dy
        elif y + WINDOW_SIZE >= sh:
            y = sh - WINDOW_SIZE
            self.dy = -self.dy
        self.move(x, y)

    # ==================== 鼠标事件 ====================
    def mousePressEvent(self, event):
        if self.is_closing:
            return
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
        elif event.button() == Qt.RightButton:
            self.show_context_menu(event.globalPos())

    def mouseMoveEvent(self, event):
        if self.dragging and not self.is_closing:
            self.move(event.globalPos() - self.drag_pos)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = False

    def mouseDoubleClickEvent(self, event):
        if self.is_closing:
            return
        if event.button() == Qt.LeftButton:
            self.fetch_and_show("__PET_TRIGGER__:双击")

    def show_context_menu(self, pos):
        if self.is_closing:
            return
            
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2d2d3f, stop:1 #1a1a2e);
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 12px;
                padding: 8px 4px;
                color: #e8e8f0;
                font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
                font-size: 13px;
            }
            QMenu::item {
                padding: 8px 32px 8px 16px;
                border-radius: 8px;
                margin: 2px 6px;
            }
            QMenu::item:selected {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7c5cfc, stop:1 #5c3dce);
                color: white;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(255,255,255,0.08);
                margin: 4px 12px;
            }
        """)
        
        menu.addAction("💬 聊聊天", lambda: self.fetch_and_show("__PET_TRIGGER__:想聊天"))
        menu.addAction("🔍 搜索", self.search_prompt)
        menu.addSeparator()
        menu.addAction("🚶 去散步", self.start_moving)
        menu.addAction("🧍 停下来", self.stop_moving)
        menu.addAction("🔄 转身", self.turn_around)
        menu.addSeparator()
        menu.addAction("🔄 清空对话", self.clear_chat_history)
        menu.addAction("❌ 退出", self.safe_exit)
        menu.exec_(pos)


# ==================== 9. 程序入口 ====================
if __name__ == "__main__":
    if not DEEPSEEK_API_KEY:
        print("❌ 未检测到 DEEPSEEK_API_KEY 环境变量。")
        print("   请先设置你的 DeepSeek API Key，例如：")
        print('   Windows (PowerShell):  $env:DEEPSEEK_API_KEY = "sk-你的密钥"')
        print('   macOS / Linux:         export DEEPSEEK_API_KEY="sk-你的密钥"')
        sys.exit(1)

    app = QApplication(sys.argv)
    
    # 设置应用字体
    font = QFont("Microsoft YaHei", 9)
    app.setFont(font)
    
    def load_and_scale(path):
        pix = QPixmap(path)
        if not pix.isNull():
            pix = pix.scaled(WINDOW_SIZE, WINDOW_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return pix

    images = {}
    image_names = ["s", "wr1", "wr2", "wr3", "wl1", "wl2", "wl3"]
    
    for name in image_names:
        pix = load_and_scale(os.path.join(script_dir, f"{name}.png"))
        if pix.isNull():
            print(f"⚠️ 警告：找不到 {name}.png，用默认色块代替")
            placeholder = QPixmap(WINDOW_SIZE, WINDOW_SIZE)
            if name == "s":
                placeholder.fill(QColor(100, 200, 255))
            elif name.startswith("wr"):
                placeholder.fill(QColor(200, 100, 100))
            elif name.startswith("wl"):
                placeholder.fill(QColor(100, 100, 200))
            images[name] = placeholder
        else:
            images[name] = pix

    pet = DesktopPet(images)
    sys.exit(app.exec_())