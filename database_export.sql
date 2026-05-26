-- MySQL dump 10.13  Distrib 8.0.41, for Win64 (x86_64)
--
-- Host: localhost    Database: stock_recommendation
-- ------------------------------------------------------
-- Server version	8.0.41

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `stock_daily_performance`
--

DROP TABLE IF EXISTS `stock_daily_performance`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `stock_daily_performance` (
  `id` int NOT NULL AUTO_INCREMENT,
  `recommendation_id` int NOT NULL,
  `trade_date` date NOT NULL,
  `current_price` decimal(10,2) NOT NULL,
  `change_percent` decimal(10,4) NOT NULL,
  `volume` bigint DEFAULT NULL,
  `turnover` decimal(20,2) DEFAULT NULL,
  `signal` enum('buy','hold','sell') COLLATE utf8mb4_unicode_ci NOT NULL,
  `signal_reason` varchar(200) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime DEFAULT (now()),
  PRIMARY KEY (`id`),
  KEY `idx_recommendation_trade` (`recommendation_id`,`trade_date`),
  KEY `ix_stock_daily_performance_trade_date` (`trade_date`),
  CONSTRAINT `stock_daily_performance_ibfk_1` FOREIGN KEY (`recommendation_id`) REFERENCES `stock_recommendations` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=21 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `stock_daily_performance`
--

LOCK TABLES `stock_daily_performance` WRITE;
/*!40000 ALTER TABLE `stock_daily_performance` DISABLE KEYS */;
INSERT INTO `stock_daily_performance` VALUES (2,32,'2026-05-21',4.40,-0.0265,NULL,NULL,'buy','首次推荐买入','2026-05-21 12:45:44'),(3,36,'2026-05-21',993.34,0.0000,NULL,NULL,'buy','首次推荐买入','2026-05-21 17:28:04'),(4,43,'2026-05-22',36.37,0.0000,NULL,NULL,'buy','首次推荐买入','2026-05-22 08:38:38'),(5,44,'2026-05-22',15.19,0.0000,NULL,NULL,'buy','首次推荐买入','2026-05-22 08:38:38'),(6,32,'2026-05-22',4.48,-0.0088,97114461,430229624.00,'hold','持有中，当前涨跌幅 -0.88%','2026-05-22 11:26:47'),(7,36,'2026-05-22',1030.96,0.0379,13105557,13387763485.00,'hold','持有中，当前涨跌幅 3.79%','2026-05-22 11:26:47'),(8,43,'2026-05-22',36.49,0.0033,105995486,3888388416.00,'hold','持有中，当前涨跌幅 0.33%','2026-05-22 11:26:47'),(9,44,'2026-05-22',15.02,-0.0112,208635392,3122562301.00,'hold','持有中，当前涨跌幅 -1.12%','2026-05-22 11:26:47'),(10,32,'2026-05-22',4.48,-0.0088,97114461,430229624.00,'hold','持有中，当前涨跌幅 -0.88%','2026-05-22 14:08:46'),(11,36,'2026-05-22',1030.96,0.0379,13105557,13387763485.00,'hold','持有中，当前涨跌幅 3.79%','2026-05-22 14:08:46'),(12,43,'2026-05-22',36.49,0.0033,105995486,3888388416.00,'hold','持有中，当前涨跌幅 0.33%','2026-05-22 14:08:46'),(13,44,'2026-05-22',15.02,-0.0112,208635392,3122562301.00,'hold','持有中，当前涨跌幅 -1.12%','2026-05-22 14:08:46'),(14,45,'2026-05-22',8.88,0.0195,NULL,NULL,'buy','首次推荐买入','2026-05-22 16:31:12'),(15,32,'2026-05-22',4.47,-0.0111,140492188,623780726.00,'hold','持有中，当前涨跌幅 -1.11%','2026-05-22 16:32:31'),(16,45,'2026-05-22',8.71,0.0000,116858144,1017949977.00,'hold','持有中，当前涨跌幅 0.00%','2026-05-22 16:32:31'),(17,32,'2026-05-22',4.47,-0.0111,140492188,623780726.00,'hold','持有中，当前涨跌幅 -1.11%','2026-05-22 16:33:05'),(18,45,'2026-05-22',8.71,-0.0180,116858144,1017949977.00,'hold','持有中，当前涨跌幅 -1.80%','2026-05-22 16:33:05'),(19,32,'2026-05-22',4.47,-0.0111,140492188,623780726.00,'hold','持有中，当前涨跌幅 -1.11%','2026-05-22 16:33:47'),(20,45,'2026-05-22',8.71,-0.0180,116858144,1017949977.00,'hold','持有中，当前涨跌幅 -1.80%','2026-05-22 16:33:47');
/*!40000 ALTER TABLE `stock_daily_performance` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `stock_recommendations`
--

DROP TABLE IF EXISTS `stock_recommendations`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `stock_recommendations` (
  `id` int NOT NULL AUTO_INCREMENT,
  `stock_code` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `stock_name` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `recommend_date` date NOT NULL,
  `recommend_price` decimal(10,2) DEFAULT NULL,
  `price_status` enum('pending','filled','void') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'filled',
  `recommend_reason` json DEFAULT NULL,
  `status` enum('active','closed') COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `close_date` date DEFAULT NULL,
  `close_price` decimal(10,2) DEFAULT NULL,
  `final_return` decimal(10,4) DEFAULT NULL,
  `created_at` datetime DEFAULT (now()),
  `is_watched` tinyint(1) NOT NULL DEFAULT '0',
  `watched_at` datetime DEFAULT NULL,
  `source` enum('system','user') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'system',
  `shares` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_code_date_src` (`stock_code`,`recommend_date`,`source`),
  KEY `ix_stock_recommendations_stock_code` (`stock_code`),
  KEY `ix_stock_recommendations_recommend_date` (`recommend_date`),
  KEY `ix_stock_recommendations_status` (`status`),
  KEY `idx_is_watched` (`is_watched`),
  KEY `idx_price_status` (`price_status`),
  KEY `idx_source` (`source`)
) ENGINE=InnoDB AUTO_INCREMENT=49 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `stock_recommendations`
--

LOCK TABLES `stock_recommendations` WRITE;
/*!40000 ALTER TABLE `stock_recommendations` DISABLE KEYS */;
INSERT INTO `stock_recommendations` VALUES (32,'003816','中国广核','2026-05-21',4.52,'filled','{\"manual\": true, \"entry_price\": 4.48}','closed','2026-05-26',4.52,0.0000,'2026-05-21 12:45:44',1,'2026-05-21 07:50:00','user',11200),(33,'002245','蔚蓝锂芯','2026-05-21',18.57,'filled','{\"ret_5\": 9.76, \"ret_20\": 36.17, \"ret_60\": 57.75, \"vol_std\": 3.99, \"position\": 5.64, \"liquidity\": 5.33, \"max_dd_20\": -3.76, \"dist_high60\": 3.76, \"total_score\": 67.16, \"trend_smooth\": 9.75, \"volume_factor\": 18.94, \"trend_strength\": 27.5, \"vol_ratio_5_20\": 1.45, \"reference_close\": 19.3}','closed',NULL,NULL,NULL,'2026-05-21 13:03:28',0,NULL,'system',0),(34,'002185','华天科技','2026-05-21',15.43,'filled','{\"ret_5\": 8.54, \"ret_20\": 24.65, \"ret_60\": 15.07, \"vol_std\": 2.64, \"position\": 0.0, \"liquidity\": 7.67, \"max_dd_20\": -3.26, \"dist_high60\": 0.0, \"total_score\": 66.68, \"trend_smooth\": 21.42, \"volume_factor\": 18.8, \"trend_strength\": 18.8, \"vol_ratio_5_20\": 1.56, \"reference_close\": 15.77}','closed',NULL,NULL,NULL,'2026-05-21 13:03:28',0,NULL,'system',0),(35,'000021','深科技','2026-05-21',37.22,'filled','{\"ret_5\": 9.36, \"ret_20\": 30.52, \"ret_60\": 34.6, \"vol_std\": 3.35, \"position\": 0.0, \"liquidity\": 9.0, \"max_dd_20\": -2.92, \"dist_high60\": 0.0, \"total_score\": 65.6, \"trend_smooth\": 16.33, \"volume_factor\": 15.67, \"trend_strength\": 24.6, \"vol_ratio_5_20\": 1.72, \"reference_close\": 37.69}','closed',NULL,NULL,NULL,'2026-05-21 13:03:28',0,NULL,'system',0),(36,'300308','中际旭创','2026-05-21',993.34,'filled','{\"ret_5\": -1.16, \"ret_20\": 21.86, \"ret_60\": 94.96, \"vol_std\": 2.86, \"position\": 5.71, \"liquidity\": 10.0, \"max_dd_20\": -8.03, \"dist_high60\": 3.8, \"total_score\": 63.16, \"trend_smooth\": 13.08, \"volume_factor\": 8.77, \"trend_strength\": 25.6, \"vol_ratio_5_20\": 0.94, \"reference_close\": 1026.39}','closed',NULL,NULL,NULL,'2026-05-21 13:03:28',0,NULL,'system',0),(37,'300623','捷捷微电','2026-05-21',32.56,'filled','{\"ret_5\": 4.3, \"ret_20\": 18.89, \"ret_60\": 2.04, \"vol_std\": 2.29, \"position\": 8.38, \"liquidity\": 1.67, \"max_dd_20\": -5.34, \"dist_high60\": 5.58, \"total_score\": 61.47, \"trend_smooth\": 21.5, \"volume_factor\": 17.22, \"trend_strength\": 12.7, \"vol_ratio_5_20\": 1.36, \"reference_close\": 33.87}','closed',NULL,NULL,NULL,'2026-05-21 13:03:28',0,NULL,'system',0),(38,'002371','北方华创','2026-05-21',663.03,'filled','{\"ret_5\": 12.91, \"ret_20\": 39.6, \"ret_60\": 38.11, \"vol_std\": 3.44, \"position\": 0.0, \"liquidity\": 9.67, \"max_dd_20\": -4.43, \"dist_high60\": 0.0, \"total_score\": 61.29, \"trend_smooth\": 13.75, \"volume_factor\": 12.57, \"trend_strength\": 25.3, \"vol_ratio_5_20\": 1.13, \"reference_close\": 693.38}','closed',NULL,NULL,NULL,'2026-05-21 13:03:28',0,NULL,'system',0),(39,'600460','士兰微','2026-05-21',31.59,'filled','{\"ret_5\": 3.43, \"ret_20\": 20.97, \"ret_60\": 6.64, \"vol_std\": 2.09, \"position\": 0.0, \"liquidity\": 5.0, \"max_dd_20\": -3.77, \"dist_high60\": 0.0, \"total_score\": 59.78, \"trend_smooth\": 24.08, \"volume_factor\": 17.8, \"trend_strength\": 12.9, \"vol_ratio_5_20\": 1.39, \"reference_close\": 32.27}','closed',NULL,NULL,NULL,'2026-05-21 13:03:28',0,NULL,'system',0),(40,'300346','南大光电','2026-05-21',56.22,'filled','{\"ret_5\": 4.04, \"ret_20\": 21.17, \"ret_60\": 10.68, \"vol_std\": 2.53, \"position\": 0.0, \"liquidity\": 8.33, \"max_dd_20\": -5.21, \"dist_high60\": 0.0, \"total_score\": 58.58, \"trend_smooth\": 21.0, \"volume_factor\": 14.45, \"trend_strength\": 14.8, \"vol_ratio_5_20\": 1.22, \"reference_close\": 58.31}','closed',NULL,NULL,NULL,'2026-05-21 13:03:28',0,NULL,'system',0),(41,'300328','宜安科技','2026-05-21',19.84,'filled','{\"ret_5\": 8.49, \"ret_20\": 19.19, \"ret_60\": 27.66, \"vol_std\": 2.52, \"position\": 0.0, \"liquidity\": 0.5, \"max_dd_20\": -5.3, \"dist_high60\": 0.0, \"total_score\": 58.1, \"trend_smooth\": 21.08, \"volume_factor\": 16.31, \"trend_strength\": 20.2, \"vol_ratio_5_20\": 1.32, \"reference_close\": 20.55}','closed',NULL,NULL,NULL,'2026-05-21 13:03:28',0,NULL,'system',0),(42,'603290','斯达半导','2026-05-21',123.78,'filled','{\"ret_5\": 2.08, \"ret_20\": 27.72, \"ret_60\": 22.97, \"vol_std\": 2.92, \"position\": 0.0, \"liquidity\": 3.5, \"max_dd_20\": -6.45, \"dist_high60\": 0.0, \"total_score\": 57.68, \"trend_smooth\": 15.17, \"volume_factor\": 19.61, \"trend_strength\": 19.4, \"vol_ratio_5_20\": 1.52, \"reference_close\": 127.2}','closed',NULL,NULL,NULL,'2026-05-21 13:03:28',0,NULL,'system',0),(43,'000021','深科技','2026-05-22',36.37,'filled','{\"ret_5\": 5.91, \"ret_20\": 24.98, \"ret_60\": 23.92, \"vol_std\": 3.54, \"industry\": \"其他\", \"position\": 11.73, \"liquidity\": 9.38, \"max_dd_20\": -3.91, \"dist_high60\": 3.91, \"total_score\": 79.17, \"trend_smooth\": 13.44, \"volume_factor\": 20.0, \"trend_strength\": 24.62, \"vol_ratio_5_20\": 1.7, \"reference_close\": 36.37}','closed',NULL,NULL,NULL,'2026-05-22 08:36:07',0,NULL,'system',0),(44,'002185','华天科技','2026-05-22',15.19,'filled','{\"ret_5\": 6.52, \"ret_20\": 19.04, \"ret_60\": 6.45, \"vol_std\": 2.9, \"industry\": \"其他\", \"position\": 13.04, \"liquidity\": 8.33, \"max_dd_20\": -4.35, \"dist_high60\": 4.35, \"total_score\": 78.76, \"trend_smooth\": 19.27, \"volume_factor\": 20.0, \"trend_strength\": 18.12, \"vol_ratio_5_20\": 1.66, \"reference_close\": 15.19}','closed',NULL,NULL,NULL,'2026-05-22 08:36:07',0,NULL,'system',0),(45,'601985','中国核电','2026-05-22',8.80,'filled','{\"manual\": true, \"entry_price\": 8.71}','active',NULL,NULL,NULL,'2026-05-22 16:31:12',1,'2026-05-22 08:31:13','user',11300),(46,'603283','赛腾股份','2026-05-23',NULL,'pending','{\"ret_5\": 9.79, \"ret_20\": 33.05, \"ret_60\": 40.89, \"vol_std\": 3.66, \"industry\": \"其他\", \"position\": 15.0, \"liquidity\": 4.74, \"max_dd_20\": -5.63, \"dist_high60\": 5.37, \"total_score\": 76.95, \"trend_smooth\": 10.79, \"volume_factor\": 20.0, \"trend_strength\": 26.42, \"vol_ratio_5_20\": 1.43, \"reference_close\": 67.19}','closed',NULL,NULL,NULL,'2026-05-23 18:19:58',0,NULL,'system',0),(47,'300814','中富电路','2026-05-23',NULL,'pending','{\"ret_5\": 7.6, \"ret_20\": 33.16, \"ret_60\": 59.14, \"vol_std\": 3.48, \"industry\": \"其他\", \"position\": 10.66, \"liquidity\": 4.04, \"max_dd_20\": -6.43, \"dist_high60\": 3.55, \"total_score\": 71.33, \"trend_smooth\": 12.54, \"volume_factor\": 17.25, \"trend_strength\": 26.84, \"vol_ratio_5_20\": 0.93, \"reference_close\": 131.16}','closed',NULL,NULL,NULL,'2026-05-23 18:19:58',0,NULL,'system',0),(48,'002747','埃斯顿','2026-05-25',28.77,'filled',NULL,'active',NULL,NULL,NULL,'2026-05-26 08:35:27',0,NULL,'user',1700);
/*!40000 ALTER TABLE `stock_recommendations` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `strategy_statistics`
--

DROP TABLE IF EXISTS `strategy_statistics`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `strategy_statistics` (
  `id` int NOT NULL AUTO_INCREMENT,
  `stat_date` date NOT NULL,
  `total_recommendations` int NOT NULL,
  `active_positions` int NOT NULL,
  `closed_positions` int NOT NULL,
  `win_count` int NOT NULL,
  `loss_count` int NOT NULL,
  `win_rate` decimal(10,4) DEFAULT NULL,
  `avg_return` decimal(10,4) DEFAULT NULL,
  `max_return` decimal(10,4) DEFAULT NULL,
  `max_loss` decimal(10,4) DEFAULT NULL,
  `total_return` decimal(10,4) DEFAULT NULL,
  `created_at` datetime DEFAULT (now()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_strategy_statistics_stat_date` (`stat_date`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `strategy_statistics`
--

LOCK TABLES `strategy_statistics` WRITE;
/*!40000 ALTER TABLE `strategy_statistics` DISABLE KEYS */;
INSERT INTO `strategy_statistics` VALUES (1,'2026-05-21',0,0,0,0,0,0.0000,0.0000,0.0000,0.0000,0.0000,'2026-05-21 08:40:45'),(2,'2026-05-22',2,2,0,0,0,0.0000,0.0000,0.0000,0.0000,0.0000,'2026-05-22 11:26:47');
/*!40000 ALTER TABLE `strategy_statistics` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Dumping routines for database 'stock_recommendation'
--
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-05-26  9:03:41
