# google-cloud-firestore is optional — app runs without it in local mode
try:
    from google.cloud import firestore
    FIRESTORE_AVAILABLE = True
except ImportError:
    firestore = None
    FIRESTORE_AVAILABLE = False

from src.core.config import settings
import logging
import os

logger = logging.getLogger(__name__)

class FirestoreClient:
    """
    Wrapper for Google Cloud Firestore.
    Used for real-time data and audit logs.
    Gracefully handles missing credentials (local testing).
    """
    def __init__(self):
        self.client = None
        self.is_connected = False
        self.emulator_host = os.getenv("FIRESTORE_EMULATOR_HOST")

    def connect(self):
        """Initialize Firestore client with graceful fallback."""
        if not FIRESTORE_AVAILABLE:
            logger.info("google-cloud-firestore not installed — Firestore disabled. Audit logs → PostgreSQL.")
            self.is_connected = False
            return False
        try:
            # Check if emulator is available (for local testing)
            if self.emulator_host:
                logger.info(f"Using Firestore Emulator at {self.emulator_host}")
            
            # Try to connect to Firestore
            try:
                self.client = firestore.AsyncClient(project=settings.GCP_PROJECT or "agentic-alpha-local")
                logger.info("Connected to Firestore")
                self.is_connected = True
                return True
            except Exception as e:
                logger.warning(f"Firestore not available: {e}")
                logger.info("Audit logs will be stored in PostgreSQL instead")
                self.is_connected = False
                return False
        except Exception as e:
            logger.error(f"Firestore initialization error: {e}")
            self.is_connected = False
            return False

    async def get_document(self, collection: str, doc_id: str):
        """Get a document with fallback."""
        try:
            if not self.is_connected or not self.client:
                logger.debug(f"Firestore not connected - cannot fetch {collection}/{doc_id}")
                return None
            
            doc_ref = self.client.collection(collection).document(doc_id)
            doc = await doc_ref.get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.warning(f"Error getting Firestore document: {e}")
            return None

    async def set_document(self, collection: str, doc_id: str, data: dict):
        """Set/Update a document with fallback."""
        try:
            if not self.is_connected or not self.client:
                logger.debug(f"Firestore not connected - caching {collection}/{doc_id} locally")
                return False
            
            doc_ref = self.client.collection(collection).document(doc_id)
            await doc_ref.set(data)
            return True
        except Exception as e:
            logger.warning(f"Error setting Firestore document: {e}")
            return False

    async def add_document(self, collection: str, data: dict):
        """Add a document with auto-generated ID with fallback."""
        try:
            if not self.is_connected or not self.client:
                logger.debug(f"Firestore not connected - storing {collection} in PostgreSQL")
                return None
            
            doc_ref = await self.client.collection(collection).add(data)
            return doc_ref.id
        except Exception as e:
            logger.warning(f"Error adding Firestore document: {e}")
            return None

    async def query_documents(self, collection: str, field: str, operator: str, value):
        """Query documents with fallback."""
        try:
            if not self.is_connected or not self.client:
                return []
            
            query = self.client.collection(collection)
            if operator == "==":
                query = query.where(field, "==", value)
            elif operator == ">=":
                query = query.where(field, ">=", value)
            elif operator == "<=":
                query = query.where(field, "<=", value)
            
            docs = await query.stream()
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            logger.warning(f"Error querying Firestore: {e}")
            return []

# Global instance - lazy initialized
db_firestore = None

def get_firestore_client() -> FirestoreClient:
    """Get or initialize the Firestore client."""
    global db_firestore
    if db_firestore is None:
        db_firestore = FirestoreClient()
        db_firestore.connect()
    return db_firestore

