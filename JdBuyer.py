# -*- coding: utf-8 -*-
import time

from config import global_config
from log import logger
from exception import JDException
from JdSession import Session
from timer import Timer
from utils import (
    save_image,
    open_image,
    send_wechat
)
from concurrence import parallel, ParallelManager


class Buyer(object):
    """
    京东买手
    """

    # 初始化
    def __init__(self):
        self.session = Session()
        # 微信推送
        self.enableWx = global_config.getboolean('messenger', 'enable')
        self.scKey = global_config.get('messenger', 'sckey')

    ############## 登录相关 #############
    # 二维码登录
    def loginByQrCode(self):
        if self.session.isLogin:
            logger.info('登录成功')
            return

        # download QR code
        qrCode = self.session.getQRcode()
        if not qrCode:
            raise JDException('二维码下载失败')

        fileName = 'QRcode.png'
        save_image(qrCode, fileName)
        logger.info('二维码获取成功，请打开京东APP扫描')
        open_image(fileName)

        # get QR code ticket
        ticket = None
        retryTimes = 85
        for i in range(retryTimes):
            ticket = self.session.getQRcodeTicket()
            if ticket:
                break
            time.sleep(2)
        else:
            raise JDException('二维码过期，请重新获取扫描')

        # validate QR code ticket
        if not self.session.validateQRcodeTicket(ticket):
            raise JDException('二维码信息校验失败')

        logger.info('二维码登录成功')
        self.session.isLogin = True
        self.session.saveCookies()

    ############## 外部方法 #############
    @parallel
    def buyItemInStock(self, skuId, areaId, skuNum=1, stockInterval=3, submitRetry=3, submitInterval=5, buyTime='2022-08-06 00:00:00'):
        """根据库存自动下单商品
        :skuId 商品sku
        :areaId 下单区域id
        :skuNum 购买数量
        :stockInterval 库存查询间隔（单位秒）
        :submitRetry 下单尝试次数
        :submitInterval 下单尝试间隔（单位秒）
        :buyTime 定时执行
        """
        self.session.fetchItemDetail(skuId)
        timer = Timer(buyTime)
        timer.start()

        while True:
            try:
                if not self.session.getItemStock(skuId, skuNum, areaId):
                    logger.info('不满足下单条件，{0}s后进行下一次查询'.format(stockInterval))
                else:
                    logger.info('{0} 满足下单条件，开始执行'.format(skuId))
                    if self.session.trySubmitOrder(skuId, skuNum, areaId, submitRetry, submitInterval):
                        logger.info('下单成功')
                        if self.enableWx:
                            send_wechat(
                                message='JdBuyerApp', 
                                desp='您的商品{0}已下单成功，请及时支付订单'.format(skuId), 
                                sckey=self.scKey)
                        return
            except Exception as e:
                logger.error(e)
            time.sleep(stockInterval)


if __name__ == '__main__':
    import json
    from argparse import ArgumentParser
    parser = ArgumentParser("JdBuyerApp")
    parser.add_argument("--config", type=str, default="shopping_cart.json", help="购物车配置文件")
    args = parser.parse_args()
    # 库存查询间隔(秒)
    stockInterval = global_config.getint('config', 'stock_interval')
    # 监听库存后尝试下单次数
    submitRetry = global_config.getint('config', 'submit_retry')
    # 下单尝试间隔(秒)
    submitInterval = global_config.getint('config', 'submit_interval')
    # 默认地址
    default_area_id = global_config.get('config', 'default_area_id')
    with open(args.config, 'r', encoding="utf-8") as f:
        config = json.load(f)
    buyer = Buyer()  # 初始化
    buyer.loginByQrCode()
    with ParallelManager() as pm:
        for idx, good in enumerate(config["goods"], 1):
            if "skuid" not in good:
                logger.error("第{0}个商品配置错误，缺少skuid".format(idx))
                exit(1)
            skuId = good["skuid"]
            areaId = good.get("areaid", default_area_id)
            skuNum = good.get("count", 1)
            buyTime = good.get("buytime", "1970-01-01 00:00:00")
            buyer.buyItemInStock(skuId, areaId, skuNum, stockInterval,
                                submitRetry, submitInterval, buyTime)
            logger.info('商品{0}监控线程已启动'.format(skuId))
