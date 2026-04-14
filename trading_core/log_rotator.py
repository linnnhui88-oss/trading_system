import os
import gzip
import shutil
from datetime import datetime, timedelta
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class LogRotator:
    """日志轮转管理器"""
    
    def __init__(self, log_dir: str, max_age_days: int = 7, max_size_mb: int = 50):
        """
        初始化日志轮转器
        
        Args:
            log_dir: 日志目录
            max_age_days: 保留天数
            max_size_mb: 单个文件最大大小(MB)
        """
        self.log_dir = Path(log_dir)
        self.max_age_days = max_age_days
        self.max_size_bytes = max_size_mb * 1024 * 1024
        
    def rotate_log(self, log_file: str) -> bool:
        """
        轮转单个日志文件
        
        Args:
            log_file: 日志文件名
            
        Returns:
            是否成功轮转
        """
        log_path = self.log_dir / log_file
        
        if not log_path.exists():
            logger.debug(f"日志文件不存在: {log_path}")
            return False
            
        file_size = log_path.stat().st_size
        
        # 检查文件大小
        if file_size < self.max_size_bytes:
            logger.debug(f"日志文件大小 {file_size / 1024 / 1024:.2f}MB，无需轮转")
            return False
            
        try:
            # 创建轮转文件名
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            rotated_name = f"{log_file}.{timestamp}"
            rotated_path = self.log_dir / rotated_name
            
            # 复制并重命名
            shutil.copy2(log_path, rotated_path)
            
            # 清空原文件（不删除，保持文件句柄有效）
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write('')  # 清空内容
                
            logger.info(f"日志已轮转: {log_file} -> {rotated_name}")
            
            # 压缩旧日志
            self._compress_old_log(rotated_path)
            
            return True
            
        except Exception as e:
            logger.error(f"日志轮转失败: {e}")
            return False
    
    def _compress_old_log(self, log_path: Path):
        """压缩旧日志文件"""
        try:
            gz_path = str(log_path) + '.gz'
            with open(log_path, 'rb') as f_in:
                with gzip.open(gz_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # 删除原文件
            log_path.unlink()
            logger.info(f"日志已压缩: {log_path.name}.gz")
            
        except Exception as e:
            logger.error(f"日志压缩失败: {e}")
    
    def cleanup_old_logs(self) -> int:
        """
        清理过期日志
        
        Returns:
            删除的文件数量
        """
        cutoff_date = datetime.now() - timedelta(days=self.max_age_days)
        deleted_count = 0
        
        try:
            for file_path in self.log_dir.iterdir():
                if not file_path.is_file():
                    continue
                    
                # 检查是否为日志文件
                if not (file_path.name.endswith('.json') or 
                        file_path.name.endswith('.json.gz') or
                        file_path.name.endswith('.log') or
                        file_path.name.endswith('.log.gz')):
                    continue
                    
                # 检查修改时间
                mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                if mtime < cutoff_date:
                    try:
                        file_path.unlink()
                        deleted_count += 1
                        logger.info(f"已删除过期日志: {file_path.name}")
                    except Exception as e:
                        logger.error(f"删除日志失败 {file_path.name}: {e}")
                        
        except Exception as e:
            logger.error(f"清理日志失败: {e}")
            
        return deleted_count
    
    def get_log_stats(self) -> dict:
        """获取日志统计信息"""
        stats = {
            'total_files': 0,
            'total_size_mb': 0,
            'log_files': []
        }
        
        try:
            for file_path in self.log_dir.iterdir():
                if not file_path.is_file():
                    continue
                    
                if file_path.suffix in ['.json', '.log', '.gz']:
                    size = file_path.stat().st_size
                    stats['total_files'] += 1
                    stats['total_size_mb'] += size / 1024 / 1024
                    stats['log_files'].append({
                        'name': file_path.name,
                        'size_mb': round(size / 1024 / 1024, 2),
                        'mtime': datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
                    })
                    
        except Exception as e:
            logger.error(f"获取日志统计失败: {e}")
            
        return stats


def rotate_signal_logs():
    """轮转信号日志（供外部调用）"""
    log_dir = Path(__file__).parent.parent / 'data'
    rotator = LogRotator(log_dir, max_age_days=7, max_size_mb=50)
    
    # 轮转主日志文件
    rotated = rotator.rotate_log('trade_signals.json')
    
    # 清理旧日志
    cleaned = rotator.cleanup_old_logs()
    
    if rotated or cleaned > 0:
        logger.info(f"日志维护完成: 轮转={rotated}, 清理={cleaned}")
    
    return rotated, cleaned


if __name__ == '__main__':
    # 测试
    logging.basicConfig(level=logging.INFO)
    rotate_signal_logs()
