import json
from datetime import date
from pathlib import Path
from sqlalchemy import select,func
from src.database import Base,engine,Session
from src.models import User,Hive,Visit
from src.auth import hash_password
from src.resource_models import FeedLot,FeedIssue,QueenObservation
from src.season_models import InsulationLot
from src.batch_models import InspectionBatch,InspectionBatchHive,InspectionReading

def seed():
    Base.metadata.create_all(engine)
    with Session() as db:
        for role in ['admin','beekeeper','viewer']:
            email=role+'@shanjing.test'
            if not db.scalar(select(User).where(User.email==email)):db.add(User(email=email,password=hash_password('Hive2026!'),role=role))
        for i in range(1,81):
            code=f'H-{i:03}'
            if not db.scalar(select(Hive).where(Hive.code==code)):db.add(Hive(code=code,site='山荆东坡' if i<=40 else '山荆林缘',queen_present=i not in [31,62],colony_frames=4 if i in [31,47,62,75] else 8,care_state='observe'))
        db.flush();hives=db.scalars(select(Hive).order_by(Hive.id)).all();reference=json.loads((Path(__file__).resolve().parents[1]/'fixtures/winter_reference.json').read_text())
        for i,values in enumerate(reference):
            code=f'V-1117-{i+1:03}';hive=hives[i%80]
            if not db.scalar(select(Visit).where(Visit.code==code)):db.add(Visit(code=code,hive_id=hive.id,queen_seen=hive.code not in ['H-031','H-062'],colony_frames=4 if hive.code in ['H-031','H-047','H-062','H-075'] else 8,**values))
        for code,kg,expiry,state in [('FD-202611-A',30,date(2027,11,30),'active'),('FD-HOLD',8,date(2027,5,1),'quarantine'),('FD-EXPIRED',5,date(2026,1,1),'active')]:
            if not db.scalar(select(FeedLot).where(FeedLot.code==code)):db.add(FeedLot(code=code,received_kg=kg,available_kg=kg,expires_on=expiry,state=state))
        if not db.scalar(select(InsulationLot).where(InsulationLot.code=='IN-2026-WINTER')):db.add(InsulationLot(code='IN-2026-WINTER',available_units=120))
        db.flush()
        # 演示批次：只补充缺失的演示批，不改人工领批、补录、接收或封存。
        demo=[h for h in hives if h.code in ['H-005','H-006','H-007']]
        if not db.scalar(select(InspectionBatch).where(InspectionBatch.code=='BAT-1117-DEMO')):
            batch=InspectionBatch(code='BAT-1117-DEMO',state='claimed',note='11月17日东坡相邻三箱，供交接演示',claimed_by='beekeeper@shanjing.test',claim_fingerprint='seed-demo',hive_count=len(demo))
            db.add(batch);db.flush()
            for seq,hive in enumerate(demo):
                db.add(InspectionBatchHive(batch_id=batch.id,hive_id=hive.id,hive_code=hive.code,site=hive.site,seq=seq,active_key=hive.id))
            db.flush()
            for hive,missing in zip(demo,[False,False,True]):
                values={'weight_kg':round(hive.id*0.1+27.5,2),'temperature':33.2,'activity':52.0,'feed_left':2.2,'queen_seen':hive.queen_present,'colony_frames':hive.colony_frames}
                if missing:values['activity']=None;values['feed_left']=None
                db.add(InspectionReading(batch_id=batch.id,hive_id=hive.id,hive_code=hive.code,**values,state='incomplete' if missing else 'complete',missing_fields=['出入蜂活动','余饲'] if missing else [],recorded_by='beekeeper@shanjing.test'))
        db.commit();print({key:db.scalar(select(func.count()).select_from(model)) for key,model in [('users',User),('hives',Hive),('visits',Visit),('batches',InspectionBatch)]})
if __name__=='__main__':seed()
