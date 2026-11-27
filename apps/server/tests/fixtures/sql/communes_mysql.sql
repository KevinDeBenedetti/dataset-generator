-- MySQL dump 10.13
/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET NAMES utf8mb4 */;

DROP TABLE IF EXISTS `communes`;
CREATE TABLE `communes` (
  `code` varchar(5) NOT NULL,
  `nom` varchar(100) DEFAULT NULL,
  `population` int(11) DEFAULT NULL,
  PRIMARY KEY (`code`),
  KEY `idx_nom` (`nom`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

LOCK TABLES `communes` WRITE;
/*!40000 ALTER TABLE `communes` DISABLE KEYS */;
INSERT INTO `communes` VALUES ('29019','Brest',139456),('29232','L\'Île; Tudy',NULL),('56121','Lorient',57149);
/*!40000 ALTER TABLE `communes` ENABLE KEYS */;
UNLOCK TABLES;
