"""
Events and Cache Management Module

Handles response listeners, chat cache with TTL, and event-driven data extraction.
"""
import time as _time
from typing import Dict, Any, Callable, Optional
import logging


class ChatCache:
    """Chat cache with TTL (Time To Live) management"""
    
    def __init__(self, ttl_seconds: int = 1800, max_size: int = 2000):
        """
        Initialize chat cache
        
        Args:
            ttl_seconds: Time to live for cache entries (default: 30 minutes)
            max_size: Maximum number of cache entries
        """
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        
    def get(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """Get cache entry by chat_id"""
        self._prune_expired()
        return self.cache.get(str(chat_id))
    
    def set(self, chat_id: str, data: Dict[str, Any]) -> None:
        """Set cache entry with current timestamp"""
        key = str(chat_id)
        data["ts"] = int(_time.time())
        self.cache[key] = data
        self._prune_expired()  # Remove expired entries first
        self._prune_cache()    # Then handle size limits
    
    def get_all(self) -> Dict[str, Dict[str, Any]]:
        """Get all cache entries (after pruning expired ones)"""
        self._prune_expired()
        return dict(self.cache)
    
    def clear(self) -> None:
        """Clear all cache entries"""
        self.cache.clear()
    
    def size(self) -> int:
        """Get current cache size"""
        return len(self.cache)
    
    def _prune_expired(self) -> None:
        """Remove expired cache entries"""
        try:
            now = int(_time.time())
            expired_keys = []
            
            for key, value in self.cache.items():
                ts = value.get("ts", now)
                if now - ts > self.ttl_seconds:
                    expired_keys.append(key)
            
            for key in expired_keys:
                self.cache.pop(key, None)
                
        except Exception:
            # Silently handle any pruning errors
            pass
    
    def _prune_cache(self) -> None:
        """Remove oldest entries if cache exceeds max size"""
        try:
            if len(self.cache) > self.max_size:
                # Remove oldest entries (those with earliest timestamps)
                sorted_items = sorted(
                    self.cache.items(), 
                    key=lambda x: x[1].get("ts", 0)
                )
                
                # Keep only the most recent max_size entries
                entries_to_remove = len(self.cache) - self.max_size
                for i in range(entries_to_remove):
                    key, _ = sorted_items[i]
                    self.cache.pop(key, None)
                    
        except Exception:
            # Silently handle any pruning errors
            pass


class ResponseListener:
    """Handles Playwright response listening and data extraction"""
    
    def __init__(self, chat_cache: ChatCache, logger: Optional[logging.Logger] = None):
        """
        Initialize response listener
        
        Args:
            chat_cache: ChatCache instance for storing extracted data
            logger: Optional logger for debugging
        """
        self.chat_cache = chat_cache
        self.logger = logger or logging.getLogger(__name__)
        self._registered = False
    
    def register(self, context) -> None:
        """Register response listener with Playwright context"""
        if self._registered:
            return
            
        try:
            def _on_response(response):
                """Handle response events and extract chat data"""
                try:
                    # Only process small JSON responses to avoid performance issues
                    if (response.request.resource_type == "xhr" and 
                        "application/json" in response.headers.get("content-type", "") and
                        int(response.headers.get("content-length", "0")) < 50000):
                        
                        # Parse JSON response
                        data = response.json()
                        
                        # Extract chat list data
                        if isinstance(data, dict) and "data" in data:
                            chat_list = data["data"]
                            if isinstance(chat_list, list):
                                for item in chat_list:
                                    if isinstance(item, dict) and "chatId" in item:
                                        # Extract relevant fields
                                        found = self._extract_chat_data(item)
                                        if found and found.get("chat_id"):
                                            self.chat_cache.set(found["chat_id"], found)
                                            
                                            if self.logger:
                                                self.logger.debug(f"Cached chat data: {found['chat_id']}")
                                            
                except BaseException as e:
                    # Silently handle ALL errors including greenlet errors
                    # Greenlet errors can occur when response callbacks fire during concurrent requests
                    error_str = str(e).lower()
                    if 'greenlet' not in error_str and 'thread' not in error_str:
                        # Log non-greenlet errors for debugging
                        if self.logger:
                            self.logger.debug(f"Response processing error: {e}")
                    return
            
            context.on("response", _on_response)
            self._registered = True
            
            if self.logger:
                self.logger.info("Response listener registered successfully")
                
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to register response listener: {e}")
    
    def _extract_chat_data(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract chat data from API response item
        
        Args:
            item: Raw chat item from API response
            
        Returns:
            Extracted chat data or None if extraction fails
        """
        try:
            # Extract basic chat information
            chat_id = item.get("chatId")
            if not chat_id:
                return None
            
            # Extract candidate information
            candidate_name = "Unknown"
            user_info = item.get("userInfo") or {}
            if isinstance(user_info, dict):
                candidate_name = user_info.get("name") or candidate_name
            
            # Extract latest message
            message = "—"
            latest_msg = item.get("latestMessage") or {}
            if isinstance(latest_msg, dict):
                message = latest_msg.get("content") or message
            
            # Extract job title
            job_title = "—"
            job_info = item.get("jobInfo") or {}
            if isinstance(job_info, dict):
                job_title = job_info.get("jobName") or job_title
            
            # Extract status
            status = "—"
            if "status" in item:
                status = str(item["status"])
            
            return {
                "chat_id": str(chat_id),
                "candidate": candidate_name,
                "message": message,
                "status": status,
                "job_title": job_title,
                "raw_data": item  # Keep original data for reference
            }
            
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Chat data extraction error: {e}")
            return None


class EventManager:
    """Manages events and cache for the Boss service"""
    
    def __init__(self, ttl_seconds: int = 1800, max_cache_size: int = 2000, 
                 logger: Optional[logging.Logger] = None):
        """
        Initialize event manager
        
        Args:
            ttl_seconds: Cache TTL in seconds
            max_cache_size: Maximum cache size
            logger: Optional logger
        """
        self.chat_cache = ChatCache(ttl_seconds, max_cache_size)
        self.response_listener = ResponseListener(self.chat_cache, logger)
        self.logger = logger or logging.getLogger(__name__)
    
    def setup(self, context) -> None:
        """Setup event listeners with Playwright context"""
        try:
            self.response_listener.register(context)
            self.logger.info("Event manager setup completed")
        except Exception as e:
            self.logger.error(f"Event manager setup failed: {e}")
    
    def get_cached_messages(self, limit: int = 10) -> list:
        """
        Get cached messages formatted for API response
        
        Args:
            limit: Maximum number of messages to return
            
        Returns:
            List of formatted message dictionaries
        """
        try:
            all_cached = self.chat_cache.get_all()
            messages = []
            
            # Convert cached data to message format
            for chat_id, cached_data in list(all_cached.items())[:limit]:
                messages.append({
                    'chat_id': cached_data.get('chat_id', chat_id),
                    'candidate': cached_data.get('candidate', 'Unknown'),
                    'message': cached_data.get('message', '—'),
                    'status': cached_data.get('status', '—'),
                    'job_title': cached_data.get('job_title', '—'),
                    'timestamp': cached_data.get('ts', 0)
                })
            
            # Sort by timestamp (newest first)
            messages.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
            
            return messages[:limit]
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error getting cached messages: {e}")
            return []
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return {
            "size": self.chat_cache.size(),
            "max_size": self.chat_cache.max_size,
            "ttl_seconds": self.chat_cache.ttl_seconds
        }
    
    def clear_cache(self) -> None:
        """Clear all cached data"""
        self.chat_cache.clear()
        if self.logger:
            self.logger.info("Cache cleared")
