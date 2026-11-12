"""Both channels share the selected categories, lock and completion-based cooldown."""
import threading
import time
import logging

logger = logging.getLogger("ValorantToxicTamer.sender")


class Sender:
    def __init__(self, messages, api, cooldown=0.5, notify=lambda _: None,
                 clock=time.monotonic, wait=None):
        self.messages, self.api = messages, api
        self.cooldown, self.notify, self.clock = cooldown, notify, clock
        self.cancel = threading.Event()
        self.wait = wait or self.cancel.wait
        self.lock = threading.RLock()
        self.busy = False
        self.ready_at = 0.0
        self.thread = None

    def trigger(self, channel):
        with self.lock:
            if self.cancel.is_set() or self.busy or self.clock() < self.ready_at:
                logger.info("trigger ignored channel=%s busy=%s cooldown=%s stopping=%s", channel,
                            self.busy, self.clock() < self.ready_at, self.cancel.is_set())
                return False
            if channel not in ("team", "all"):
                return False
            if not self.messages.current:
                self.notify("当前发送范围没有消息，请勾选类别或添加消息。")
                return False
            target = self.api.target()
            if not target:
                detail = getattr(self.api, "target_error", "无法确认无畏契约在前台")
                self.notify(f"已忽略：{detail}。")
                return False
            if self.api.modifiers_down():
                self.notify("已忽略：请先松开 Shift / Ctrl / Alt / Win。")
                return False
            self.busy = True
            logger.info("input starting channel=%s hwnd=%s pid=%s", channel, *target)
            self.thread = threading.Thread(target=self._run,
                args=(channel, target, self.messages.current), name="message-sender")
            try:
                self.thread.start()
            except Exception:
                self.busy = False
                self.thread = None
                raise
            return True

    def edit(self, action):
        with self.lock:
            if self.busy:
                raise ValueError("正在输入，请稍后再修改消息或设置。")
            return action()

    def _run(self, channel, target, message):
        held = set()

        def check():
            if self.cancel.is_set():
                raise RuntimeError("程序正在退出")
            if not self.api.is_foreground(target):
                raise RuntimeError("游戏前台窗口发生变化，已中止输入")

        def down(vk):
            check()
            held.add(vk)
            self.api.key(vk, True)

        def up(vk):
            self.api.key(vk, False)
            held.discard(vk)

        def pause(seconds):
            self.wait(seconds)
            check()

        try:
            check()
            if self.api.modifiers_down():
                raise RuntimeError("检测到修饰键按下，请松开后重试")
            if channel == "all":
                logger.info("opening all chat: batched Shift+Enter down, lead=0ms hold=80ms tail=30ms")
                check()
                # Either event may have been submitted if SendInput partially fails.
                held.update((0x10, 0x0D))
                self.api.keys((0x10, 0x0D), True)
            else:
                down(0x0D)
            pause(0.08 if channel == "all" else 0.03)
            up(0x0D)
            if channel == "all":
                pause(0.03)
                up(0x10)
            pause(0.15)
            for character in message:
                check()
                if self.api.modifiers_down():
                    raise RuntimeError("输入期间检测到修饰键，已中止")
                self.api.text_character(character)
                # No per-character sleep; keep cancellation/focus checks per character.
            pause(0.05)
            if self.api.modifiers_down():
                raise RuntimeError("发送前检测到修饰键，已中止")
            down(0x0D)
            pause(0.03)
            up(0x0D)
            with self.lock:
                self.messages.advance()
            status = f"{'队伍' if channel == 'team' else '全体'}输入流程完成（未验证聊天框及服务器送达）。"
        except Exception as exc:
            status = f"输入中止，索引未推进：{exc}。重试前请关闭聊天框并检查残留文本。"
        finally:
            failures = []
            for vk in sorted(held):  # Release Enter before Shift on failure.
                try:
                    self.api.key(vk, False)
                except Exception as exc:
                    failures.append(str(exc))
            with self.lock:
                self.ready_at = self.clock() + self.cooldown
                self.busy = False
            if failures:
                status += " 按键释放失败，请手动按下并松开 Shift / Enter。"
            self.notify(status)

    def stop(self):
        self.cancel.set()
        if self.thread and self.thread.is_alive():
            self.thread.join()
