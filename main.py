from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain, At
from typing import Dict, List, Set
import asyncio

@register("three_garden", "开发者", "QQ群逛三园小游戏插件", "1.0.0", "https://github.com/...")
class ThreeGardenGame(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.games: Dict[str, GameSession] = {}  # 群号到游戏会话的映射
        
    class GameSession:
        def __init__(self):
            self.players: List[Dict] = []        # 玩家列表（含QQ号和状态）
            self.theme: str = ""                # 当前主题
            self.used_words: Set[str] = set()    # 已用词汇
            self.current_player: int = 0        # 当前玩家索引
            self.timer_task = None              # 计时器任务
            self.game_status = 0                # 0-未开始 1-进行中
            self.max_time = 30                  # 单次回答时限（秒）
# 开始游戏指令
@filter.command("开始三园", group_only=True)
async def start_game(self, event: AstrMessageEvent):
    group_id = event.group_id
    if group_id in self.games:
        yield event.chain_result([Plain("当前群组已有进行中的游戏！")])
        return
    
    self.games[group_id] = self.GameSession()
    game = self.games[group_id]
    game.theme = "水果园"  # 可扩展为主题选择功能
    game.game_status = 1
    
    yield event.chain_result([
        Plain("【逛三园游戏开始】\n"),
        Plain(f"主题：{game.theme}\n"),
        Plain("发送「加入三园」参与游戏！\n"),
        Plain("主持人可发送「结束三园」终止游戏")
    ])

# 玩家加入指令
@filter.command("加入三园", group_only=True)
async def join_game(self, event: AstrMessageEvent):
    group_id = event.group_id
    if group_id not in self.games:
        return
    
    user_id = event.sender.user_id
    if any(p["user_id"] == user_id for p in self.games[group_id].players):
        yield event.chain_result([Plain("您已加入游戏！")])
        return
    
    self.games[group_id].players.append({
        "user_id": user_id,
        "name": event.get_sender_name(),
        "status": "active"
    })
    
    yield event.chain_result([
        At(qq=user_id),
        Plain(" 已加入游戏！当前玩家数："),
        Plain(str(len(self.games[group_id].players)))
    ])
async def game_round(self, group_id: str):
    game = self.games[group_id]
    while len([p for p in game.players if p["status"] == "active"]) > 1:
        current = game.players[game.current_player]
        if current["status"] != "active":
            game.current_player = (game.current_player + 1) % len(game.players)
            continue
            
        # 发送提示消息
        await self.context.bot.send_group_msg(
            group_id=group_id,
            message=[
                At(qq=current["user_id"]),
                Plain(f" 请回答{game.theme}相关词汇（剩余时间：{game.max_time}秒）")
            ]
        )
        
        # 启动计时器
        game.timer_task = asyncio.create_task(self.countdown(group_id))
        
        # 等待玩家回应
        try:
            await asyncio.wait_for(
                self.wait_for_answer(group_id, current["user_id"]),
                timeout=game.max_time
            )
        except asyncio.TimeoutError:
            await self.handle_timeout(group_id, current)
        
        game.current_player = (game.current_player + 1) % len(game.players)

async def wait_for_answer(self, group_id: str, user_id: int):
    event = await self.context.wait_for(
        lambda e: isinstance(e, AstrMessageEvent) 
        and e.group_id == group_id 
        and e.sender.user_id == user_id
    )
    return self.process_answer(event)

async def process_answer(self, event: AstrMessageEvent):
    answer = event.message_str.strip()
    game = self.games[event.group_id]
    
    if answer in game.used_words:
        yield event.chain_result([
            At(qq=event.sender.user_id),
            Plain(" 该词汇已被使用！")
        ])
        return False
    
    # 此处可扩展验证逻辑（如调用第三方API验证水果名称）
    if is_valid_answer(answer, game.theme):  # 需要实现验证函数
        game.used_words.add(answer)
        return True
    else:
        yield event.chain_result([
            At(qq=event.sender.user_id),
            Plain(" 回答不符合主题！")
        ])
        return False
async def handle_timeout(self, group_id: str, player: dict):
    game = self.games[group_id]
    player["status"] = "eliminated"
    
    await self.context.bot.send_group_msg(
        group_id=group_id,
        message=[
            At(qq=player["user_id"]),
            Plain(" 超时未回答，淘汰！")
        ]
    )
    
    active_players = [p for p in game.players if p["status"] == "active"]
    if len(active_players) == 1:
        winner = active_players[0]
        await self.end_game(group_id, winner)
        
async def end_game(self, group_id: str, winner: dict = None):
    game = self.games.pop(group_id, None)
    if game and game.timer_task:
        game.timer_task.cancel()
        
    if winner:
        msg = [
            Plain("🎉 游戏结束！获胜者是："),
            At(qq=winner["user_id"]),
            Plain("\n🏆 正确答案列表：\n"),
            Plain("\n".join(game.used_words))
        ]
    else:
        msg = [Plain("游戏已终止")]
        
    await self.context.bot.send_group_msg(
        group_id=group_id,
        message=msg
    )
