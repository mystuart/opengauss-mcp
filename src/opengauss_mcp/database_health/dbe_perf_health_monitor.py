import logging
from datetime import datetime, timedelta
from typing import Any
from typing import LiteralString
from typing import Union
from typing import cast

from ..sql import SafeSqlDriver
from ..sql import SqlDriver
from ..sql.extension_utils import get_database_type

logger = logging.getLogger(__name__)


class DbePerfHealthMonitor:
    """Tool for monitoring database health using various dbe_perf views."""
    
    def __init__(self, sql_driver: Union[SqlDriver, SafeSqlDriver]):
        self.sql_driver = sql_driver
        
    
    async def get_global_file_iostat(self, hours: int = 24) -> str:
        """Get global file I/O statistics from dbe_perf.global_file_iostat view.

        Args:
            hours: Number of hours to analyze (default: 24)

        Returns:
            Formatted string with global file I/O statistics
        """
        try:
            # Check database type
            db_type = await get_database_type(self.sql_driver)
            if db_type != "opengauss":
                logger.warning(f"dbe_perf views are only available in openGauss, not in {db_type}")
                return "This feature is only available in openGauss database."
            
            # Query global file I/O statistics with correct field names
            query = cast(
                LiteralString,
                """
                SELECT
                    node_name,
                    filenum,
                    dbid,
                    spcid,
                    phyrds,
                    phywrts,
                    phyblkrd,
                    phyblkwrt,
                    readtim,
                    writetim,
                    avgiotim,
                    lstiotim,
                    miniotim,
                    maxiowtm
                FROM dbe_perf.global_file_iostat
                WHERE phyrds > 0 OR phywrts > 0
                ORDER BY phyrds + phywrts DESC
                LIMIT 50
                """
            )
            
            logger.debug(f"Executing global file I/O stats query for {hours} hours")
            result = await self.sql_driver.execute_query(query)
            
            if not result:
                return "No global file I/O statistics found."
            
            # Format results
            result_text = [f"Global File I/O Statistics (top 50 files):"]
            
            for row in result:
                file_stat = row.cells
                result_text.append(f"\nFile Number: {file_stat['filenum']}")
                result_text.append(f"  Node: {file_stat['node_name']}")
                result_text.append(f"  Database ID: {file_stat['dbid']}")
                result_text.append(f"  Tablespace ID: {file_stat['spcid']}")
                result_text.append(f"  Physical Reads: {file_stat['phyrds']}")
                result_text.append(f"  Physical Writes: {file_stat['phywrts']}")
                result_text.append(f"  Physical Blocks Read: {file_stat['phyblkrd']}")
                result_text.append(f"  Physical Blocks Written: {file_stat['phyblkwrt']}")
                
                read_time = file_stat.get("readtim")
                write_time = file_stat.get("writetim")
                if read_time is not None and read_time > 0:
                    result_text.append(f"  Read Time: {read_time} ms")
                if write_time is not None and write_time > 0:
                    result_text.append(f"  Write Time: {write_time} ms")
                
                avg_io_time = file_stat.get("avgiotim")
                if avg_io_time is not None and avg_io_time > 0:
                    result_text.append(f"  Average IO Time: {avg_io_time} ms")
                
                last_io_time = file_stat.get("lstiotim")
                if last_io_time is not None and last_io_time > 0:
                    result_text.append(f"  Last IO Time: {last_io_time} ms")
                
                min_io_time = file_stat.get("miniotim")
                if min_io_time is not None and min_io_time > 0:
                    result_text.append(f"  Min IO Time: {min_io_time} ms")
                
                max_io_wait_time = file_stat.get("maxiowtm")
                if max_io_wait_time is not None and max_io_wait_time > 0:
                    result_text.append(f"  Max IO Wait Time: {max_io_wait_time} ms")
            
            return "\n".join(result_text)
        except Exception as e:
            logger.error(f"Error getting global file I/O stats: {e}")
            return f"Error getting global file I/O stats: {e}"
    
    async def get_global_wait_events(self, hours: int = 24) -> str:
        """Get global wait events from dbe_perf.global_wait_events view.

        Args:
            hours: Number of hours to analyze (default: 24)

        Returns:
            Formatted string with global wait events
        """
        try:
            # Check database type
            db_type = await get_database_type(self.sql_driver)
            if db_type != "opengauss":
                logger.warning(f"dbe_perf views are only available in openGauss, not in {db_type}")
                return "This feature is only available in openGauss database."
            
            # Query global wait events with correct field names
            query = cast(
                LiteralString,
                """
                SELECT
                    nodename,
                    "type",
                    "event",
                    "wait",
                    failed_wait,
                    total_wait_time,
                    avg_wait_time,
                    max_wait_time,
                    min_wait_time,
                    last_updated
                FROM dbe_perf.global_wait_events
                WHERE "wait" > 0
                ORDER BY total_wait_time DESC
                LIMIT 30
                """
            )
            
            logger.debug(f"Executing global wait events query for {hours} hours")
            result = await self.sql_driver.execute_query(query)
            
            if not result:
                return "No global wait events found."
            
            # Format results
            result_text = [f"Global Wait Events (top 30 by total wait time):"]
            
            for row in result:
                wait_event = row.cells
                result_text.append(f"\nEvent: {wait_event['event']}")
                result_text.append(f"  Node: {wait_event['nodename']}")
                result_text.append(f"  Type: {wait_event['type']}")
                result_text.append(f"  Wait Count: {wait_event['wait']}")
                result_text.append(f"  Failed Wait Count: {wait_event['failed_wait']}")
                result_text.append(f"  Total Wait Time: {wait_event['total_wait_time']} ms")
                result_text.append(f"  Avg Wait Time: {wait_event['avg_wait_time']} ms")
                result_text.append(f"  Max Wait Time: {wait_event['max_wait_time']} ms")
                result_text.append(f"  Min Wait Time: {wait_event['min_wait_time']} ms")
                result_text.append(f"  Last Updated: {wait_event['last_updated']}")
            
            return "\n".join(result_text)
        except Exception as e:
            logger.error(f"Error getting global wait events: {e}")
            return f"Error getting global wait events: {e}"
    
    
    async def get_comprehensive_health_report(self) -> str:
        """Get a comprehensive health report using available dbe_perf views.

        Returns:
            Formatted string with comprehensive health report
        """
        try:
            # Check database type
            db_type = await get_database_type(self.sql_driver)
            if db_type != "opengauss":
                logger.warning(f"dbe_perf views are only available in openGauss, not in {db_type}")
                return "This feature is only available in openGauss database."
            
            # Get statistics from available views
            wait_events = await self.get_global_wait_events()
            file_iostat = await self.get_global_file_iostat()
            
            # Format comprehensive report
            result = ["COMPREHENSIVE DATABASE HEALTH REPORT"]
            result.append("=" * 50)
            
            # Add summary of each section
            result.append("\n1. WAIT EVENTS")
            result.append("-" * 30)
            result.append(wait_events)
            
            result.append("\n2. FILE I/O STATISTICS")
            result.append("-" * 30)
            result.append(file_iostat)
            
            result.append("\nHEALTH ANALYSIS")
            result.append("-" * 30)
            
            # Add basic health analysis
            result.append("\n- Wait Events Analysis:")
            if "No global wait events found." in wait_events:
                result.append("  No significant wait events detected.")
            else:
                result.append("  Significant wait events detected. Review wait events section.")
            
            result.append("\n- File I/O Analysis:")
            if "No global file I/O statistics found." in file_iostat:
                result.append("  No file I/O statistics available.")
            else:
                result.append("  File I/O statistics available. Review file I/O section.")
            
            return "\n".join(result)
        except Exception as e:
            logger.error(f"Error getting comprehensive health report: {e}")
            return f"Error getting comprehensive health report: {e}"